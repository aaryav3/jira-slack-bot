# debug_jira_fields.py - Run this to find the Share Chat URL field ID

import os
from dotenv import load_dotenv
from jira import JIRA

load_dotenv()

def find_share_url_field():
    """Find the custom field ID for Share Chat URL"""
    
    try:
        # Initialize Jira client
        jira_client = JIRA(
            server=os.getenv("JIRA_API_SERVER"),
            basic_auth=(os.getenv("JIRA_USER_EMAIL"), os.getenv("JIRA_API_TOKEN"))
        )
        
        print("=== FINDING SHARE CHAT URL FIELD ===")
        
        # Get all custom fields
        all_fields = jira_client.fields()
        
        print("\nLooking for potential Share Chat URL fields...")
        potential_fields = []
        
        for field in all_fields:
            field_name = field.get('name', '').lower()
            field_id = field.get('id', '')
            
            # Look for fields containing relevant keywords
            if any(keyword in field_name for keyword in ['share', 'chat', 'url', 'link']):
                potential_fields.append(field)
                print(f"  Found: {field_id} - {field['name']}")
        
        # Get project metadata to see what fields are available for Bug issues
        print(f"\nChecking available fields for Bug issues in project {os.getenv('JIRA_PROJECT_KEY')}...")
        
        project_meta = jira_client.createmeta(
            projectKeys=os.getenv("JIRA_PROJECT_KEY"), 
            expand='projects.issuetypes.fields'
        )
        
        for project in project_meta['projects']:
            for issuetype in project['issuetypes']:
                if issuetype['name'] == 'Bug':
                    fields = issuetype['fields']
                    
                    print(f"\nAll custom fields available for Bug issues:")
                    share_url_candidates = []
                    
                    for field_id, field_data in fields.items():
                        if field_id.startswith('customfield_'):
                            field_name = field_data.get('name', 'Unknown')
                            field_type = field_data.get('schema', {}).get('type', 'unknown')
                            required = field_data.get('required', False)
                            
                            print(f"  {field_id}: {field_name} (Type: {field_type}, Required: {required})")
                            
                            # Check if this could be our Share Chat URL field
                            if any(keyword in field_name.lower() for keyword in ['share', 'chat', 'url', 'link']):
                                share_url_candidates.append((field_id, field_name))
                                print(f"    *** POTENTIAL SHARE CHAT URL FIELD ***")
                    
                    if share_url_candidates:
                        print(f"\n🎯 Share Chat URL field candidates:")
                        for field_id, field_name in share_url_candidates:
                            print(f"   {field_id}: {field_name}")
                    else:
                        print(f"\n❌ No Share Chat URL field found. You may need to:")
                        print(f"   1. Create a custom field called 'Share Chat URL' in Jira")
                        print(f"   2. Add it to the Bug issue type screen")
                        print(f"   3. Make it available for your project")
        
        print("\n=== END DEBUG ===")
        
        if not potential_fields:
            print("\n⚠️  No Share Chat URL field found!")
            print("Next steps:")
            print("1. Create a custom field in Jira called 'Share Chat URL'")
            print("2. Set it as type 'URL' or 'Text'") 
            print("3. Add it to the Bug issue type's Create/Edit screens")
            print("4. Run this script again to find the field ID")
            print("5. Update jira_helper.py with the correct field ID")
        
    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure your .env file has the correct Jira credentials:")
        print("JIRA_API_SERVER=https://yourcompany.atlassian.net")
        print("JIRA_USER_EMAIL=your-email@company.com")
        print("JIRA_API_TOKEN=your-api-token")
        print("JIRA_PROJECT_KEY=YOUR-PROJECT-KEY")

if __name__ == "__main__":
    find_share_url_field()


# requirements.txt
"""
flask==2.3.3
slack-sdk==3.21.3
jira==3.5.0
python-dotenv==1.0.0
requests==2.31.0
"""

# SETUP INSTRUCTIONS
"""
=== SETUP INSTRUCTIONS FOR AUTO BUG DETECTION BOT ===

1. INSTALL DEPENDENCIES:
   pip install flask slack-sdk jira python-dotenv requests

2. UPDATE YOUR .ENV FILE:
   Add these if not already present:
   SLACK_BOT_TOKEN=xoxb-your-token
   JIRA_USER_EMAIL=your-email@company.com
   JIRA_API_TOKEN=your-jira-token
   JIRA_API_SERVER=https://yourcompany.atlassian.net
   JIRA_PROJECT_KEY=YOUR-PROJECT
   SLACK_SERVER=https://yourworkspace.slack.com

3. FIND SHARE CHAT URL FIELD:
   python debug_jira_fields.py
   
   If no field is found, create one in Jira:
   - Go to Jira Settings > Issues > Custom Fields
   - Create new field: "Share Chat URL" (type: URL or Text)
   - Add to Bug issue type screens
   - Run debug script again to get the field ID

4. UPDATE JIRA_HELPER.PY:
   Replace 'customfield_10038' with the actual field ID from step 3

5. UPDATE SLACK APP PERMISSIONS:
   In Slack App settings, ensure you have these scopes:
   - channels:history
   - channels:read
   - chat:write
   - app_mentions:read
   - reactions:read    (NEW - needed for emoji confirmations)
   - reactions:write   (NEW - needed to add confirmation reactions)

6. TEST THE BOT:
   - Start the app: python app.py
   - In Slack, write any message in a channel where the bot is added
   - Bot should ask for confirmation with checkmark emoji
   - React with ✅ to create ticket

=== NEW FEATURES SUMMARY ===

✅ AUTO BUG DETECTION: Bot detects potential bug reports automatically
✅ EMOJI CONFIRMATIONS: React with ✅ to confirm bug creation  
✅ SMART PARSING: Auto-detects environment (Prod/Dev/Stage) and product
✅ URL VALIDATION: Handles share URLs and converts chat URLs
✅ THREAD MONITORING: Waits for user responses in threads
✅ LEGACY SUPPORT: All old ! commands still work
✅ BETTER ERROR HANDLING: Graceful failure and user feedback

=== BEHAVIOR CHANGES ===

BEFORE: Only responded to !bug commands
AFTER: Responds to ANY message in channels (not threads)

BEFORE: Required manual environment/product specification
AFTER: Auto-detects from message content, defaults to Prod/Clientell AI

BEFORE: No URL handling
AFTER: Extracts and validates share URLs, converts chat URLs

BEFORE: Simple command-response
AFTER: Interactive confirmation with emoji reactions
"""

# Test the message parser
def test_message_parser():
    """Test the message parsing functionality"""
    
    from message_parser import MessageParser
    
    test_cases = [
        "Login not working in prod. The user dashboard is broken.",
        "Dataloader crashing in dev environment https://dev.clientell.ai/share/123-456",
        "Bug in staging with clientell AI: https://app.clientell.ai/chat/abc-def",
        "This is a very long bug description that exceeds 255 characters. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco. This part should be description.",
        "Simple bug report without environment specified"
    ]
    
    print("=== TESTING MESSAGE PARSER ===")
    
    for i, message in enumerate(test_cases, 1):
        print(f"\nTest {i}: {message[:50]}...")
        result = MessageParser.parse_message(message)
        
        print(f"  Title: {result['title']}")
        print(f"  Description: {result['description'][:50]}{'...' if len(result['description']) > 50 else ''}")
        print(f"  Environment: {result['environment']}")
        print(f"  Product: {result['product']}")
        print(f"  Share URLs: {result['urls']['share_urls']}")
        print(f"  Chat URLs: {result['urls']['chat_urls']}")

if __name__ == "__main__":
    print("Choose an option:")
    print("1. Find Jira Share Chat URL field")
    print("2. Test message parser")
    
    choice = input("Enter 1 or 2: ").strip()
    
    if choice == "1":
        find_share_url_field()
    elif choice == "2":
        test_message_parser()
    else:
        print("Invalid choice")