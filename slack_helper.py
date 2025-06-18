from slack_sdk.errors import SlackApiError
from config import EnvironmentSettings
from slack_sdk import WebClient
import re
import time
import threading

slack_client = WebClient(token=EnvironmentSettings.get_slack_bot_token())

# Store pending confirmations {confirmation_message_ts: original_message_data}
pending_confirmations = {}
# Store pending URL requests {thread_ts: ticket_data}
pending_url_requests = {}

def get_slack_user_email(user_id):
    """Get user email from Slack user ID (if permissions available)"""
    if not user_id:
        return None
        
    try:
        user_info = slack_client.users_info(user=user_id)
        if user_info and user_info.get('ok') and user_info.get('user', {}).get('profile', {}).get('email'):
            return user_info['user']['profile']['email']
        else:
            print(f"No email found for user {user_id}")
            return None
    except SlackApiError as e:
        print(f"Error retrieving user info for {user_id}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error retrieving user info for {user_id}: {e}")
        return None

def get_parent_message(channel_id, thread_ts):
    """Get the parent message text from a thread"""
    if not channel_id or not thread_ts:
        return None
        
    try:
        response = slack_client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = response.get('messages', [])
        if messages:
            return messages[0].get('text')
    except SlackApiError as e:
        print(f"Error fetching thread message: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching thread message: {e}")
        return None

def post_message(channel, thread_ts, text):
    """Post a message to Slack"""
    try:
        response = slack_client.chat_postMessage(
            channel=channel, 
            thread_ts=thread_ts, 
            text=text
        )
        return response
    except SlackApiError as e:
        print(f"Error posting message: {e}")
        return None

def add_reaction(channel, timestamp, emoji):
    """Add emoji reaction to a message"""
    try:
        response = slack_client.reactions_add(
            channel=channel,
            timestamp=timestamp,
            name=emoji
        )
        return response.get('ok', False)
    except SlackApiError as e:
        print(f"Error adding reaction: {e}")
        return False

def ask_for_bug_confirmation(channel, original_message_ts, user_id, parsed_data):
    """Ask user to confirm if message is a bug report"""
    try:
        # VALIDATION: Ensure we have all required data
        if not parsed_data or not isinstance(parsed_data, dict):
            print(f"❌ Invalid parsed_data received: {parsed_data}")
            return None
        
        # Extract fields with safe defaults
        title = parsed_data.get('title', 'Unknown Title')
        environment = parsed_data.get('environment', 'Unknown Environment')
        product = parsed_data.get('product', 'Unknown Product')
        description = parsed_data.get('description', '').strip()
        urls = parsed_data.get('urls', {'share_urls': [], 'chat_urls': []})
        
        print(f"🐛 Building confirmation message with:")
        print(f"   Title: {title}")
        print(f"   Environment: {environment}")
        print(f"   Product: {product}")
        print(f"   Description length: {len(description)}")
        print(f"   URLs: {urls}")
        
        # Build confirmation message with all fields
        confirmation_text = (
            f"🐛 Hi <@{user_id}>, I detected this might be a bug report:\n\n"
            f"**Title:** {title}\n"
            f"**Environment:** {environment}\n"
            f"**Product:** {product}\n"
        )
        
        # Add description if it exists
        if description:
            # Truncate description if too long for preview
            if len(description) > 200:
                description_preview = description[:200] + "..."
            else:
                description_preview = description
            confirmation_text += f"**Description:** {description_preview}\n"
        else:
            confirmation_text += f"**Description:** _(No additional description)_\n"
        
        # Add URL information with safe handling
        share_urls = urls.get('share_urls', []) if isinstance(urls, dict) else []
        chat_urls = urls.get('chat_urls', []) if isinstance(urls, dict) else []
        
        if share_urls:
            confirmation_text += f"**Share URL:** {share_urls[0]} ✅\n"
        elif chat_urls:
            confirmation_text += f"**Chat URL:** {chat_urls[0]} (will ask for share URL) 🔗\n"
        else:
            confirmation_text += f"**URL:** _(No URL provided)_\n"
        
        confirmation_text += f"\nReact with ✅ to create a Jira ticket, or ignore this message to skip."
        
        print(f"📤 Posting confirmation message: {len(confirmation_text)} characters")
        
        # Post confirmation message
        response = post_message(channel, original_message_ts, confirmation_text)
        
        if response and response.get('ok'):
            confirmation_msg_ts = response['ts']
            
            # Store the confirmation data with the CONFIRMATION message timestamp as key
            pending_confirmations[confirmation_msg_ts] = {
                'user_id': user_id,
                'channel': channel,
                'original_message_ts': original_message_ts,
                'parsed_data': parsed_data,
                'timestamp': time.time()
            }
            
            # Add reaction option
            add_reaction(channel, confirmation_msg_ts, 'white_check_mark')
            
            print(f"✅ Confirmation posted successfully: {confirmation_msg_ts}")
            return confirmation_msg_ts
        else:
            print(f"❌ Failed to post confirmation message: {response}")
            return None
        
    except Exception as e:
        print(f"💥 ERROR in ask_for_bug_confirmation: {e}")
        import traceback
        traceback.print_exc()
        return None

def handle_confirmation_reaction(channel, message_ts, user_id):
    """Handle reaction on confirmation message - INSTANT processing"""
    try:
        print(f"🎯 Reaction detected on message {message_ts} by user {user_id}")
        
        # Check if this message timestamp is a pending confirmation
        if message_ts not in pending_confirmations:
            print(f"❌ Message {message_ts} not found in pending confirmations")
            print(f"📋 Current pending confirmations: {list(pending_confirmations.keys())}")
            return False
        
        confirmation_data = pending_confirmations[message_ts]
        
        # Verify it's the same user who originally sent the message
        if confirmation_data['user_id'] != user_id:
            print(f"❌ User mismatch. Expected {confirmation_data['user_id']}, got {user_id}")
            return False
        
        print(f"✅ Valid confirmation reaction detected! Processing bug report...")
        
        # Get the data
        parsed_data = confirmation_data['parsed_data']
        original_message_ts = confirmation_data['original_message_ts']
        
        # Process the confirmed bug report immediately
        process_confirmed_bug_report(confirmation_data, original_message_ts)
        
        # Clean up
        del pending_confirmations[message_ts]
        
        return True
        
    except Exception as e:
        print(f"Error handling confirmation reaction: {e}")
        return False

def process_confirmed_bug_report(confirmation_data, original_message_ts):
    """Process confirmed bug report immediately"""
    try:
        parsed_data = confirmation_data['parsed_data']
        user_id = confirmation_data['user_id']
        channel = confirmation_data['channel']
        
        print(f"🚀 Processing confirmed bug report for user {user_id}")
        
        # Check URL handling
        urls = parsed_data['urls']
        
        if urls['share_urls']:
            # We have valid share URLs - create ticket immediately
            share_url = urls['share_urls'][0]
            print(f"📎 Share URL found: {share_url}")
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, share_url)
            
        elif urls['chat_urls']:
            # We have chat URLs - ask for share URL conversion
            chat_url = urls['chat_urls'][0]
            print(f"💬 Chat URL found: {chat_url}")
            ask_for_share_url_conversion(parsed_data, user_id, channel, original_message_ts, chat_url)
            
        else:
            # No URLs - create ticket without URL
            print(f"📝 No URLs found - creating ticket without share URL")
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, None)
        
    except Exception as e:
        print(f"Error processing confirmed bug report: {e}")

def ask_for_share_url_conversion(parsed_data, user_id, channel, original_message_ts, chat_url):
    """Ask user to convert chat URL to share URL"""
    try:
        # Store the pending URL request
        pending_url_requests[original_message_ts] = {
            'parsed_data': parsed_data,
            'user_id': user_id,
            'channel': channel,
            'original_message_ts': original_message_ts,
            'chat_url': chat_url,
            'timestamp': time.time(),
            'monitoring_active': True  # Track if monitoring is active
        }
        
        # Ask for share URL with clear 5-minute timer
        url_request_message = (
            f"🔗 Hi <@{user_id}>, I found a chat URL in your message:\n"
            f"`{chat_url}`\n\n"
            f"Please create a **share link** for this chat and paste it here in the thread. "
            f"Share links should look like: `https://app.clientell.ai/share/...`\n\n"
            f"⏰ **I'll wait exactly 5 minutes for your response**, then create the ticket without the share URL."
        )
        
        post_message(channel, original_message_ts, url_request_message)
        
        # Start monitoring thread for response with explicit 5-minute timeout
        def monitor_with_proper_timeout():
            timeout_seconds = 300  # 5 minutes = 300 seconds
            start_time = time.time()
            check_interval = 10  # Check every 10 seconds
            
            print(f"🔍 Starting 5-minute timer for thread {original_message_ts}")
            
            while True:
                current_time = time.time()
                elapsed = current_time - start_time
                remaining = timeout_seconds - elapsed
                
                # Check if we've reached the timeout
                if elapsed >= timeout_seconds:
                    print(f"⏰ 5-minute timeout reached! Creating ticket without share URL")
                    if original_message_ts in pending_url_requests:
                        post_message(channel, original_message_ts, "⏰ Timeout reached. Creating ticket without share URL...")
                        create_ticket_with_url(original_message_ts)
                    break
                
                # Check if request was already processed
                if original_message_ts not in pending_url_requests:
                    print(f"✅ Request already processed, stopping timer")
                    break
                
                # Check if monitoring was disabled
                if not pending_url_requests[original_message_ts].get('monitoring_active', True):
                    print(f"🛑 Monitoring disabled, stopping timer")
                    break
                
                # Show remaining time
                if int(remaining) % 60 == 0:  # Log every minute
                    print(f"⏳ Timer: {int(remaining/60)} minutes remaining")
                
                # Wait before next check
                time.sleep(min(check_interval, remaining))
        
        # Start the monitoring thread
        monitor_thread = threading.Thread(target=monitor_with_proper_timeout)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        print(f"🚀 Started 5-minute timer for URL response")
        
    except Exception as e:
        print(f"Error asking for share URL conversion: {e}")

def monitor_thread_for_url_response(channel, thread_ts, user_id, timeout_seconds=300):
    """Monitor thread for URL response with timeout"""
    def monitor():
        start_time = time.time()
        last_check = thread_ts
        
        print(f"🔍 Started monitoring thread {thread_ts} for URL response")
        
        while (time.time() - start_time) < timeout_seconds:
            try:
                # Check if we already got a response
                if thread_ts not in pending_url_requests:
                    print(f"✅ URL request already processed for {thread_ts}")
                    return
                
                # Get new messages in thread
                response = slack_client.conversations_replies(channel=channel, ts=thread_ts, oldest=last_check)
                messages = response.get('messages', [])
                
                for message in messages:
                    # Skip the original message and bot messages
                    if message['ts'] == thread_ts or message.get('user') == slack_client.auth_test()['user_id']:
                        continue
                        
                    # Check if message is from the same user
                    if message.get('user') == user_id:
                        text = message.get('text', '')
                        urls = extract_urls_from_text(text)
                        
                        if urls['share_urls']:
                            # Valid share URL found
                            print(f"✅ Share URL received: {urls['share_urls'][0]}")
                            pending_url_requests[thread_ts]['share_url'] = urls['share_urls'][0]
                            post_message(channel, thread_ts, "✅ Share URL received! Creating ticket...")
                            create_ticket_with_url(thread_ts)
                            return
                        else:
                            # Invalid response - react with X
                            add_reaction(channel, message['ts'], 'x')
                            post_message(channel, thread_ts, "❌ Invalid URL format. Creating ticket without share URL...")
                            create_ticket_with_url(thread_ts)
                            return
                    
                    last_check = message['ts']
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                print(f"Error monitoring thread: {e}")
                break
        
        # Timeout reached
        print(f"⏰ Timeout reached for thread {thread_ts}")
        if thread_ts in pending_url_requests:
            post_message(channel, thread_ts, "⏰ Timeout reached. Creating ticket without share URL...")
            create_ticket_with_url(thread_ts)
    
    # Start monitoring in background thread
    monitor_thread = threading.Thread(target=monitor)
    monitor_thread.daemon = True
    monitor_thread.start()

def create_ticket_with_url(thread_ts):
    """Create ticket for a pending URL request"""
    try:
        if thread_ts not in pending_url_requests:
            print(f"⚠️ Thread {thread_ts} not found in pending requests")
            return
        
        url_data = pending_url_requests[thread_ts]
        parsed_data = url_data['parsed_data']
        user_id = url_data['user_id']
        channel = url_data['channel']
        original_message_ts = url_data['original_message_ts']
        share_url = url_data.get('share_url')
        
        # Disable monitoring to prevent duplicate processing
        url_data['monitoring_active'] = False
        
        print(f"🎫 Creating ticket for thread {thread_ts} with share_url: {share_url}")
        
        # Create the ticket
        create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, share_url)
        
        # Clean up
        del pending_url_requests[thread_ts]
        
    except Exception as e:
        print(f"Error creating ticket with URL: {e}")

def create_ticket_immediately(parsed_data, user_id, channel, message_ts, share_url=None):
    """Create Jira ticket immediately with parsed data"""
    try:
        print(f"🎫 Creating Jira ticket for user {user_id}")
        
        # Import here to avoid circular imports
        import jira_helper
        
        # Create the Jira ticket
        created_issue = jira_helper.create_auto_bug(
            parsed_data=parsed_data,
            slack_user_id=user_id,
            channel_id=channel,
            message_ts=message_ts,
            share_url=share_url
        )
        
        # Get the ticket URL
        issue_link = created_issue.permalink()
        
        # Build success message in the legacy format
        success_message = f"✅ Your new bug ticket has been created here: {issue_link}"
        
        # Build comprehensive details message
        details_parts = ["**Ticket Details:**"]
        details_parts.append(f"• **Title:** {parsed_data['title']}")
        details_parts.append(f"• **Environment:** {parsed_data['environment']}")
        details_parts.append(f"• **Product:** {parsed_data['product']}")
        
        # Add description if it exists
        description = parsed_data.get('description', '').strip()
        if description:
            # Truncate long descriptions for the success message
            if len(description) > 100:
                desc_preview = description[:100] + "..."
            else:
                desc_preview = description
            details_parts.append(f"• **Description:** {desc_preview}")
        else:
            details_parts.append(f"• **Description:** _(No additional description)_")
        
        # Add share URL info
        if share_url:
            details_parts.append(f"• **Share URL:** Included ✅")
        else:
            # Check if there were any URLs in the original message
            urls = parsed_data.get('urls', {'share_urls': [], 'chat_urls': []})
            if urls['chat_urls']:
                details_parts.append(f"• **URL:** Chat URL was provided (no share URL)")
            else:
                details_parts.append(f"• **URL:** No URL provided")
        
        details_message = "\n".join(details_parts)
        
        # Post success message
        post_message(channel, message_ts, success_message)
        
        # Post details in the same thread
        post_message(channel, message_ts, details_message)
        
        print(f"✅ Ticket created successfully: {issue_link}")
        
    except Exception as e:
        error_message = f"❌ Failed to create bug ticket: {str(e)}"
        post_message(channel, message_ts, error_message)
        print(f"❌ Ticket creation failed: {e}")

def extract_urls_from_text(text):
    """Extract and categorize URLs from text"""
    if not text:
        return {'share_urls': [], 'chat_urls': []}
    
    # Patterns for different URL types
    share_patterns = [
        r'https://app\.clientell\.ai/share/[a-f0-9-]+',
        r'https://dev\.clientell\.ai/share/[a-f0-9-]+',
        r'https://test\.clientell\.ai/share/[a-f0-9-]+'
    ]
    
    chat_patterns = [
        r'https://app\.clientell\.ai/chat/[a-f0-9-]+',
        r'https://dev\.clientell\.ai/chat/[a-f0-9-]+',
        r'https://test\.clientell\.ai/chat/[a-f0-9-]+'
    ]
    
    share_urls = []
    chat_urls = []
    
    # Find share URLs
    for pattern in share_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        share_urls.extend(matches)
    
    # Find chat URLs
    for pattern in chat_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        chat_urls.extend(matches)
    
    return {
        'share_urls': list(set(share_urls)),  # Remove duplicates
        'chat_urls': list(set(chat_urls))
    }

def cleanup_old_pending_requests():
    """Clean up old pending requests (run periodically)"""
    current_time = time.time()
    timeout = 600  # 10 minutes
    
    # Clean confirmations
    expired_confirmations = [
        ts for ts, data in pending_confirmations.items()
        if current_time - data['timestamp'] > timeout
    ]
    for ts in expired_confirmations:
        print(f"🧹 Cleaning up expired confirmation: {ts}")
        del pending_confirmations[ts]
    
    # Clean URL requests
    expired_url_requests = [
        ts for ts, data in pending_url_requests.items()
        if current_time - data.get('timestamp', 0) > timeout
    ]
    for ts in expired_url_requests:
        print(f"🧹 Cleaning up expired URL request: {ts}")
        del pending_url_requests[ts]

def handle_confirmation_reaction(channel, message_ts, user_id):
    """Handle reaction on confirmation message - INSTANT processing"""
    try:
        print(f"🎯 Reaction detected on message {message_ts} by user {user_id}")
        
        # Check if this message timestamp is a pending confirmation
        if message_ts not in pending_confirmations:
            print(f"❌ Message {message_ts} not found in pending confirmations")
            print(f"📋 Current pending confirmations: {list(pending_confirmations.keys())}")
            return False
        
        confirmation_data = pending_confirmations[message_ts]
        
        # Verify it's the same user who originally sent the message
        if confirmation_data['user_id'] != user_id:
            print(f"❌ User mismatch. Expected {confirmation_data['user_id']}, got {user_id}")
            return False
        
        print(f"✅ Valid confirmation reaction detected! Processing bug report...")
        
        # Get the data
        parsed_data = confirmation_data['parsed_data']
        original_message_ts = confirmation_data['original_message_ts']
        
        # Process the confirmed bug report immediately
        process_confirmed_bug_report(confirmation_data, original_message_ts)
        
        # Clean up
        del pending_confirmations[message_ts]
        
        return True
        
    except Exception as e:
        print(f"Error handling confirmation reaction: {e}")
        return False

def process_confirmed_bug_report(confirmation_data, original_message_ts):
    """Process confirmed bug report immediately"""
    try:
        parsed_data = confirmation_data['parsed_data']
        user_id = confirmation_data['user_id']
        channel = confirmation_data['channel']
        
        print(f"🚀 Processing confirmed bug report for user {user_id}")
        
        # Check URL handling
        urls = parsed_data['urls']
        
        if urls['share_urls']:
            # We have valid share URLs - create ticket immediately
            share_url = urls['share_urls'][0]
            print(f"📎 Share URL found: {share_url}")
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, share_url)
            
        elif urls['chat_urls']:
            # We have chat URLs - ask for share URL conversion
            chat_url = urls['chat_urls'][0]
            print(f"💬 Chat URL found: {chat_url}")
            ask_for_share_url_conversion(parsed_data, user_id, channel, original_message_ts, chat_url)
            
        else:
            # No URLs - create ticket without URL
            print(f"📝 No URLs found - creating ticket without share URL")
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, None)
        
    except Exception as e:
        print(f"Error processing confirmed bug report: {e}")

def create_ticket_immediately(parsed_data, user_id, channel, message_ts, share_url=None):
    """Create Jira ticket immediately with parsed data"""
    try:
        print(f"🎫 Creating Jira ticket for user {user_id}")
        
        # Import here to avoid circular imports
        import jira_helper
        
        # Create the Jira ticket
        created_issue = jira_helper.create_auto_bug(
            parsed_data=parsed_data,
            slack_user_id=user_id,
            channel_id=channel,
            message_ts=message_ts,
            share_url=share_url
        )
        
        # Get the ticket URL
        issue_link = created_issue.permalink()
        
        # Build success message in the legacy format
        success_message = f"✅ Your new bug ticket has been created here: {issue_link}"
        
        # Add additional details in thread
        details_message = (
            f"**Ticket Details:**\n"
            f"• **Title:** {parsed_data['title']}\n"
            f"• **Environment:** {parsed_data['environment']}\n"
            f"• **Product:** {parsed_data['product']}"
        )
        
        if share_url:
            details_message += f"\n• **Share URL:** Included ✅"
        
        # Post success message
        post_message(channel, message_ts, success_message)
        
        # Post details in the same thread
        post_message(channel, message_ts, details_message)
        
        print(f"✅ Ticket created successfully: {issue_link}")
        
    except Exception as e:
        error_message = f"❌ Failed to create bug ticket: {str(e)}"
        post_message(channel, message_ts, error_message)
        print(f"❌ Ticket creation failed: {e}")