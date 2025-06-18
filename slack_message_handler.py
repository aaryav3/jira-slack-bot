from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import slack_helper
from config import EnvironmentSettings
import jira_helper
import time
import threading
from message_parser import MessageParser

slack_client = WebClient(token=EnvironmentSettings.get_slack_bot_token())

# Store active ticket creation processes
active_ticket_processes = {}

def handle_message(event_data):
    """Main message handler - handles both auto-detection and legacy commands"""
    text = event_data.get('text', '')
    channel = event_data['channel']
    user_id = event_data['user']
    message_ts = event_data['ts']
    
    # Check if message is in a thread (we ignore thread messages for auto-detection)
    is_thread_message = 'thread_ts' in event_data and event_data['thread_ts'] != message_ts
    
    # Get bot info to avoid responding to own messages
    try:
        bot_info = slack_client.auth_test()
        bot_user_id = bot_info['user_id']
    except:
        print("Error getting bot info")
        return
    
    # Don't respond to bot's own messages
    if user_id == bot_user_id:
        return
    
    # ADD THESE LINES:
    print(f"📨 Message received: '{text[:50]}...' from user {user_id}")
    print(f"🔍 Is thread message: {is_thread_message}")
    
    # Handle legacy commands (always respond to these regardless of thread status)
    if text.startswith('!'):
        print(f"🤖 Handling legacy command: {text}")
        handle_legacy_commands(event_data)
        return
    
    # Auto-detection logic: only for non-thread messages
    if not is_thread_message:
        print(f"🎯 Triggering auto-detection for channel message")
        handle_auto_bug_detection(text, channel, user_id, message_ts)
    else:
        # This is a thread message - check if it's a response to a URL request
        thread_ts = event_data['thread_ts']
        print(f"💬 Thread message detected, checking for URL response")
        handle_thread_response(text, channel, user_id, message_ts, thread_ts)

def handle_auto_bug_detection(text, channel, user_id, message_ts):
    """Auto-detect potential bug reports from channel messages"""
    try:
        # Skip very short messages (likely not bug reports)
        if len(text.strip()) < 10:
            print(f"⏭️ Skipping short message: '{text}'")
            return
        
        # Skip messages that are clearly not bug reports
        skip_phrases = ['thanks', 'thank you', 'good morning', 'hello', 'hi ', 'hey ', 'lol', 'haha', '👍', '👌', 'nice', 'great', 'awesome']
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in skip_phrases) and len(text) < 50:
            print(f"⏭️ Skipping non-bug message: '{text}'")
            return
        
        print(f"🔍 Parsing message: '{text[:100]}...'")
        
        # Parse the message content with validation
        try:
            parsed_data = MessageParser.parse_message(text)
            
            # VALIDATION: Ensure all required fields are present
            required_fields = ['title', 'description', 'environment', 'product', 'urls', 'original_text']
            missing_fields = [field for field in required_fields if field not in parsed_data]
            
            if missing_fields:
                print(f"❌ PARSING ERROR: Missing fields {missing_fields}")
                print(f"📋 Raw parsed_data: {parsed_data}")
                return
            
            # VALIDATION: Ensure URLs structure is correct
            if 'urls' in parsed_data and not isinstance(parsed_data['urls'], dict):
                print(f"❌ PARSING ERROR: URLs field is not a dict: {parsed_data['urls']}")
                return
            
            if 'share_urls' not in parsed_data['urls'] or 'chat_urls' not in parsed_data['urls']:
                print(f"❌ PARSING ERROR: URLs missing share_urls or chat_urls")
                return
                
        except Exception as parsing_error:
            print(f"❌ MESSAGE PARSING FAILED: {parsing_error}")
            print(f"📝 Original text: '{text}'")
            return
        
        # DEBUG: Log all parsed data
        print(f"✅ PARSING SUCCESSFUL:")
        print(f"   📝 Title: '{parsed_data['title']}'")
        print(f"   🌍 Environment: '{parsed_data['environment']}'")
        print(f"   📦 Product: '{parsed_data['product']}'")
        print(f"   📄 Description: '{parsed_data['description'][:50]}{'...' if len(parsed_data['description']) > 50 else ''}'")
        print(f"   🔗 Share URLs: {parsed_data['urls']['share_urls']}")
        print(f"   💬 Chat URLs: {parsed_data['urls']['chat_urls']}")
        
        # VALIDATION: Ensure we have meaningful content
        if not parsed_data['title'] or parsed_data['title'] == 'Bug Report':
            print(f"⚠️ WARNING: Generic title detected, but proceeding...")
        
        # Ask for confirmation with validated data
        confirmation_msg_ts = slack_helper.ask_for_bug_confirmation(channel, message_ts, user_id, parsed_data)
        
        if confirmation_msg_ts:
            print(f"✅ Confirmation request posted: {confirmation_msg_ts}")
        else:
            print(f"❌ Failed to post confirmation request")
            
    except Exception as e:
        print(f"💥 ERROR in auto bug detection: {e}")
        import traceback
        traceback.print_exc()

def handle_reaction_event(event_data):
    """
    Handle emoji reactions for bug confirmation
    """
    try:
        reaction = event_data.get('reaction')
        user_id = event_data.get('user')
        
        # Check if this is a confirmation reaction
        if reaction in ['white_check_mark', 'completed', 'check', '✅']:
            message_ts = event_data.get('item', {}).get('ts')
            
            # Find the original message this reaction is responding to
            # We need to look up the thread to find the original message
            channel = event_data.get('item', {}).get('channel')
            
            # Look for pending confirmation
            original_ts = None
            for ts, data in slack_helper.pending_confirmations.items():
                if data['channel'] == channel and data['user_id'] == user_id:
                    # This might be our confirmation
                    original_ts = ts
                    break
            
            if original_ts and original_ts in slack_helper.pending_confirmations:
                process_confirmed_bug_report(original_ts)
                
    except Exception as e:
        print(f"Error handling reaction: {e}")

def handle_thread_response(text, channel, user_id, message_ts, thread_ts):
    """Handle responses in threads (particularly for URL corrections)"""
    try:
        # Check if this thread is waiting for a URL response
        if thread_ts in slack_helper.pending_url_requests:
            url_request_data = slack_helper.pending_url_requests[thread_ts]
            
            # Check if this message is from the right user
            if url_request_data.get('user_id') == user_id:
                print(f"🔗 Processing URL response from user {user_id}")
                
                # Extract URLs from the response
                urls = MessageParser.extract_urls(text)
                
                if urls['share_urls']:
                    # Valid share URL provided
                    url_request_data['share_url'] = urls['share_urls'][0]
                    slack_helper.post_message(channel, thread_ts, "✅ Share URL received! Creating ticket...")
                    slack_helper.create_ticket_with_url(thread_ts)
                else:
                    # Invalid response
                    slack_helper.add_reaction(channel, message_ts, 'x')
                    slack_helper.post_message(channel, thread_ts, "❌ Invalid URL format. Creating ticket without share URL...")
                    slack_helper.create_ticket_with_url(thread_ts)
        else:
            print(f"ℹ️ Thread {thread_ts} not waiting for URL response")
                
    except Exception as e:
        print(f"Error handling thread response: {e}")

def process_confirmed_bug_report(original_message_ts):
    """
    Process a confirmed bug report (user reacted with checkmark)
    """
    try:
        if original_message_ts not in slack_helper.pending_confirmations:
            return
        
        confirmation_data = slack_helper.pending_confirmations[original_message_ts]
        parsed_data = confirmation_data['parsed_data']
        user_id = confirmation_data['user_id']
        channel = confirmation_data['channel']
        
        # Check if we have URLs to handle
        urls = parsed_data['urls']
        
        if urls['share_urls']:
            # We have valid share URLs - create ticket immediately
            share_url = urls['share_urls'][0]
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, share_url)
            
        elif urls['chat_urls']:
            # We have chat URLs - ask for share URL conversion
            chat_url = urls['chat_urls'][0]
            ask_for_share_url_conversion(parsed_data, user_id, channel, original_message_ts, chat_url)
            
        else:
            # No URLs - create ticket without URL
            create_ticket_immediately(parsed_data, user_id, channel, original_message_ts, None)
        
        # Clean up
        del slack_helper.pending_confirmations[original_message_ts]
        
    except Exception as e:
        print(f"Error processing confirmed bug report: {e}")

def monitor_thread_for_url_response(channel, thread_ts, user_id, timeout_seconds=300):
    """Monitor thread for URL response with proper 5-minute timeout"""
    def monitor():
        start_time = time.time()
        check_interval = 5  # Check every 5 seconds
        
        print(f"🔍 Started monitoring thread {thread_ts} for URL response (timeout: {timeout_seconds}s)")
        
        while True:
            current_time = time.time()
            elapsed_time = current_time - start_time
            
            # Check if timeout reached
            if elapsed_time >= timeout_seconds:
                print(f"⏰ Timeout reached after {elapsed_time:.1f} seconds")
                break
            
            try:
                # Check if we already got a response (processed elsewhere)
                if thread_ts not in pending_url_requests:
                    print(f"✅ URL request already processed for {thread_ts}")
                    return
                
                # Get new messages in thread since last check
                try:
                    response = slack_client.conversations_replies(
                        channel=channel, 
                        ts=thread_ts,
                        oldest=str(start_time)  # Only get messages since we started monitoring
                    )
                    messages = response.get('messages', [])
                except Exception as slack_error:
                    print(f"⚠️ Error fetching thread messages: {slack_error}")
                    time.sleep(check_interval)
                    continue
                
                # Check each message for URL responses
                for message in messages:
                    # Skip the original message and bot messages
                    if (message['ts'] == thread_ts or 
                        message.get('user') == slack_client.auth_test()['user_id'] or
                        float(message['ts']) <= start_time):
                        continue
                        
                    # Check if message is from the expected user
                    if message.get('user') == user_id:
                        text = message.get('text', '')
                        print(f"📝 Received response from user: '{text[:50]}...'")
                        
                        # Extract URLs from the response
                        urls = extract_urls_from_text(text)
                        
                        if urls['share_urls']:
                            # Valid share URL found
                            print(f"✅ Share URL received: {urls['share_urls'][0]}")
                            if thread_ts in pending_url_requests:
                                pending_url_requests[thread_ts]['share_url'] = urls['share_urls'][0]
                                post_message(channel, thread_ts, "✅ Share URL received! Creating ticket...")
                                create_ticket_with_url(thread_ts)
                                return
                        else:
                            # Invalid response - react with X
                            print(f"❌ Invalid URL format in response")
                            add_reaction(channel, message['ts'], 'x')
                            post_message(channel, thread_ts, "❌ Invalid URL format. Creating ticket without share URL...")
                            create_ticket_with_url(thread_ts)
                            return
                
                # Wait before next check
                remaining_time = timeout_seconds - elapsed_time
                print(f"⏳ Monitoring... {remaining_time:.0f}s remaining")
                time.sleep(min(check_interval, remaining_time))
                
            except Exception as e:
                print(f"⚠️ Error in monitoring loop: {e}")
                time.sleep(check_interval)
        
        # Timeout reached - create ticket without URL
        print(f"⏰ Timeout reached after {timeout_seconds} seconds")
        if thread_ts in pending_url_requests:
            post_message(channel, thread_ts, "⏰ Timeout reached. Creating ticket without share URL...")
            create_ticket_with_url(thread_ts)
    
    # Start monitoring in background thread
    monitor_thread = threading.Thread(target=monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    print(f"🚀 Started monitoring thread in background")


def handle_legacy_commands(event_data):
    """
    Handle the original ! commands for backward compatibility
    """
    text = event_data['text']
    channel = event_data['channel']
    thread_ts = event_data['thread_ts'] if "thread_ts" in event_data else event_data['ts']
    user_id = event_data['user']

    if text.startswith('!bug '):
        _respond_bug_command(user_id, text, channel, thread_ts)
    elif text.startswith("!story "):
        _respond_story_command(user_id, text, channel, thread_ts)
    elif text.startswith("!task "):
        _respond_task_command(user_id, text, channel, thread_ts)
    elif text.startswith("!epic "):
        _respond_epic_command(user_id, text, channel, thread_ts)
    elif text.startswith("!priority"):
        _respond_priority_command(channel, thread_ts)
    elif text.startswith("!inprogress "):
        _respond_in_progress_command(channel, thread_ts, text)
    elif text.startswith("!time "):
        _respond_time_command(channel, thread_ts, text)
    elif text.startswith("!help"):
        _respond_help_command(channel, thread_ts)

def handle_reaction_added(event_data):
    """Handle emoji reactions for bug confirmation - INSTANT processing"""
    try:
        reaction = event_data.get('reaction')
        user_id = event_data.get('user')
        item = event_data.get('item', {})
        channel = item.get('channel')
        message_ts = item.get('ts')
        
        print(f"👍 Reaction detected: {reaction} on message {message_ts} by user {user_id}")
        
        # Only handle checkmark reactions
        if reaction in ['white_check_mark', 'heavy_check_mark', 'check', 'ballot_box_with_check', '✅']:
            print(f"✅ Checkmark reaction detected - processing confirmation")
            
            # Handle the confirmation reaction immediately
            success = slack_helper.handle_confirmation_reaction(channel, message_ts, user_id)
            
            if success:
                print(f"🎉 Confirmation reaction processed successfully")
            else:
                print(f"❌ Failed to process confirmation reaction")
        else:
            print(f"ℹ️ Ignoring non-checkmark reaction: {reaction}")
            
    except Exception as e:
        print(f"Error handling reaction: {e}")

# Legacy command functions (keeping for backward compatibility)
def _post_message(channel, thread_ts, text):
    return slack_helper.post_message(channel, thread_ts, text)

def _remove_command_from_title(text, command):
    return text.replace(f"{command} ", "").replace(command, "").strip()

def _respond_bug_command(user_id, text, channel, thread_ts):
    bug_title = _remove_command_from_title(text, "!bug")
    if bug_title == "":
        response = (
            "Please provide a title for your bug ticket! A sample command looks like this: `!bug This is a ticket "
            "title`")
        _post_message(channel, thread_ts, response)
        return
    
    try:
        created_issue = jira_helper.create_bug(bug_title, user_id, channel, thread_ts)
        issue_link = created_issue.permalink()
        response = f"✅ Your new bug ticket has been created here: {issue_link}"
        _post_message(channel, thread_ts, response)
    except Exception as e:
        error_msg = f"❌ Failed to create bug ticket: {str(e)}"
        _post_message(channel, thread_ts, error_msg)

def _respond_story_command(user_id, text, channel, thread_ts):
    story_title = _remove_command_from_title(text, "!story")
    if story_title == "":
        response = ("Please provide a title for your story ticket! A sample command looks like this: `!story This "
                    "is a ticket title`")
        _post_message(channel, thread_ts, response)
        return
    
    try:
        created_issue = jira_helper.create_story(story_title, user_id, channel, thread_ts)
        issue_link = created_issue.permalink()
        response = f"✅ Your new story ticket has been created here: {issue_link}"
        _post_message(channel, thread_ts, response)
    except Exception as e:
        error_msg = f"❌ Failed to create story ticket: {str(e)}"
        _post_message(channel, thread_ts, error_msg)

def _respond_task_command(user_id, text, channel, thread_ts):
    task_title = _remove_command_from_title(text, "!task")
    if task_title == "":
        response = (
            "Please provide a title for your task ticket! A sample command looks like this: "
            "`!task This is a ticket title`")
        _post_message(channel, thread_ts, response)
        return
    
    try:
        created_issue = jira_helper.create_task(task_title, user_id, channel, thread_ts)
        issue_link = created_issue.permalink()
        response = f"✅ Your new task ticket has been created here: {issue_link}"
        _post_message(channel, thread_ts, response)
    except Exception as e:
        error_msg = f"❌ Failed to create task ticket: {str(e)}"
        _post_message(channel, thread_ts, error_msg)

def _respond_epic_command(user_id, text, channel, thread_ts):
    epic_title = _remove_command_from_title(text, "!epic")
    if epic_title == "":
        response = (
            "Please provide a title for your epic ticket! A sample command looks like this: "
            "`!epic This is a ticket title`")
        _post_message(channel, thread_ts, response)
        return
    
    try:
        created_issue = jira_helper.create_epic(epic_title, user_id, channel, thread_ts)
        issue_link = created_issue.permalink()
        response = f"✅ Your new epic ticket has been created here: {issue_link}"
        _post_message(channel, thread_ts, response)
    except Exception as e:
        error_msg = f"❌ Failed to create epic ticket: {str(e)}"
        _post_message(channel, thread_ts, error_msg)

def _respond_priority_command(channel, thread_ts):
    response = (
        "Thanks for reporting your issue. For us to prioritize the issue appropriately, could you please provide "
        "the following information:\n\n"
        "1. Is this problem blocking any critical release? _[Yes | No]_\n"
        "2. In which environments have you observed the issue? _[Production | Staging | Development]_\n"
        "3. What is the estimated extent of production user impact? _[Affects large | medium | small number of "
        "users]_\n"
        "4. Have you identified any workaround? _[Yes | No]_\n"
        "5. How often are you able to reproduce this issue? _[Always | Sometimes | Rarely]_\n"
        "6. What is your expected timeline for resolving this issue? _[Immediate | Within 24 hours | This week | "
        "Longer]_\n"
        "7. How severe is the impact of this issue on user experience? _[Critical | High | Medium | Low]_")
    _post_message(channel, thread_ts, response)

def _respond_in_progress_command(channel, thread_ts, text):
    slack_user_mentioned_name = text.split('!inprogress')[1].strip()
    if not slack_user_mentioned_name.startswith('<@') or not slack_user_mentioned_name.endswith('>'):
        _post_message(channel, thread_ts, "Invalid user ID format. Please use the format <@USERID>.")
        return
    slack_user_id = slack_user_mentioned_name.replace('<@', '').replace('>', '')
    user_email = slack_helper.get_slack_user_email(slack_user_id)
    assigned_tasks = jira_helper.get_assigned_tasks(user_email)
    task_list = []
    for index, task in enumerate(assigned_tasks, start=1):
        task_string = f"{index}. _*{task['priority']}*_ - <{task['url']}|{task['ticket_id']} - {task['title']}> in *{task['state']}*."
        task_list.append(task_string)
    if len(task_list) == 0:
        response = f":construction: {slack_user_mentioned_name} has *no tasks* assigned that is in progress."
    else:
        response = f":construction: {slack_user_mentioned_name} is *currently working* on the following ticket(s):\n\n" + "\n".join(
            task_list)
    _post_message(channel, thread_ts, response)

def _respond_time_command(channel, thread_ts, text):
    ticket_id = text.split('!time')[1].strip()
    if ticket_id is None or ticket_id == "":
        response = "Please provide a ticket ID to get the elapsed time for each state transition."
        _post_message(channel, thread_ts, response)
        return
    try:
        elapsed_time_list = jira_helper.get_elapsed_time_for_each_jira_ticket_state(ticket_id)
    except Exception as e:
        _post_message(channel, thread_ts, f"Error getting elapsed time for ticket *{ticket_id.upper()}*: {e}")

    try:
        story_size_priority_dict = jira_helper.get_story_size_priority(ticket_id)
    except Exception as e:
        story_size_priority_dict = {
            "size": "None",
            "priority": "None"
        }

    elapse_times_joined_message = []

    def format_duration(duration):
        minutes, seconds = divmod(duration.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration_string = ""
        if duration.days > 0:
            duration_string += f"{duration.days} day(s) "
        if hours > 0:
            duration_string += f"{hours} hour(s) "
        if minutes > 0:
            duration_string += f"{minutes} minute(s) "
        if seconds > 0:
            duration_string += f"{seconds} second(s)"

        return duration_string.strip()

    for index, time in enumerate(elapsed_time_list, start=1):
        formatted_time = format_duration(time["elapsed_time"])
        if len(elapsed_time_list) == index:
            elapse_times_joined_message.append(
                f"{index}. :here: Currently in *{time['state']}* state for *{formatted_time}*.")
        else:
            elapse_times_joined_message.append(
                f"{index}. Stayed in *{time['state']}* state for *{formatted_time}*.")

    response = f"The elapsed time for each state of ticket *{ticket_id.upper()}* with *{story_size_priority_dict['size']} points* and *{story_size_priority_dict['priority']} priority* as follows:\n\n" + "\n".join(
        elapse_times_joined_message)

    _post_message(channel, thread_ts, response)

def _respond_help_command(channel, thread_ts):
    response = (
        "Here are the commands you can use with me:\n\n"
        "**Auto Bug Detection:**\n"
        "• Just write a message in the channel - I'll detect potential bugs automatically!\n"
        "• React with ✅ to confirm and create a Jira ticket\n\n"
        "**Manual Commands:**\n"
        "• `!bug <title>` - Create a new bug ticket with the provided title\n"
        "• `!story <title>` - Create a new story ticket with the provided title\n"
        "• `!task <title>` - Create a new task ticket with the provided title\n"
        "• `!epic <title>` - Create a new epic ticket with the provided title\n"
        "• `!priority` - Get the list of questions to prioritize an issue\n"
        "• `!inprogress <@USERID>` - Get the list of tasks that a user is currently working on\n"
        "• `!time <ticket_id>` - Get the elapsed time for each state transition for a ticket\n"
        "• `!help` - Get this help message\n"
    )
    _post_message(channel, thread_ts, response)

# Cleanup function to run periodically
def cleanup_old_requests():
    """Clean up old pending requests"""
    slack_helper.cleanup_old_pending_requests()