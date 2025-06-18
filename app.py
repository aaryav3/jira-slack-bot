from flask import Flask, request, jsonify, Response
import json
import slack_message_handler as slack_handler
import logging
import threading
import time

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Background cleanup thread
def background_cleanup():
    """Run periodic cleanup of old requests"""
    while True:
        try:
            slack_handler.cleanup_old_requests()
            time.sleep(300)  # Run every 5 minutes
        except Exception as e:
            logging.error(f"Error in background cleanup: {e}")

# Start background cleanup thread
cleanup_thread = threading.Thread(target=background_cleanup)
cleanup_thread.daemon = True
cleanup_thread.start()

@app.route('/')
def index():
    return "Clientell Jira-Slack Bot v2.0 - Auto Bug Detection with Instant Reactions ⚡"

@app.route('/slack/events', methods=['POST'])
def slack_events():
    print(f"📨 Received request: {request.data}")
    print(f"📋 Headers: {dict(request.headers)}")
    
    try:
        data = json.loads(request.data)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON received: {e}")
        return jsonify({'error': 'Invalid JSON'}), 400
    
    # Slack sends a challenge request when you register the URL
    if 'challenge' in data:
        print("🤝 Responding to Slack challenge")
        return jsonify({'challenge': data['challenge']})

    # Handle retry header with proper case handling
    headers_lower = {k.lower(): v for k, v in request.headers.items()}
    
    # Skip retried requests to avoid duplicate processing
    if 'x-slack-retry-num' in headers_lower:
        logging.info("⏭️ Skipping retry request")
        response = Response(json.dumps({'status': 'ok'}), mimetype='application/json')
        response.headers['x-slack-no-retry'] = '1'
        return response

    # Process the event
    try:
        if 'event' in data:
            event = data['event']
            event_type = event.get('type')
            
            print(f"🎯 Processing event type: {event_type}")
        
            if event_type == 'message':
                # Handle message events (including auto-detection)
                if 'subtype' not in event:  # Skip bot messages and other subtypes
                    print(f"💬 Processing message event")
                    slack_handler.handle_message(event)
                else:
                    print(f"⏭️ Skipping message with subtype: {event.get('subtype')}")
                    
            elif event_type == 'reaction_added':
                # Handle emoji reactions for confirmations - THIS IS THE KEY FIX
                print(f"👍 Processing reaction_added event")
                slack_handler.handle_reaction_added(event)
            elif event_type == 'app_mention':
                # Handle @bot mentions (treat as messages)
                if 'subtype' not in event:
                    print(f"📢 Processing app mention")
                    slack_handler.handle_message(event)
                else:
                    print(f"⏭️ Skipping app mention with subtype: {event.get('subtype')}")
            
            else:
                print(f"ℹ️ Unhandled event type: {event_type}")
                
    except Exception as e:
        logging.error(f"💥 Error handling Slack event: {e}")
        import traceback
        traceback.print_exc()
        # Don't crash the endpoint - just log and continue

    response = Response(json.dumps({'status': 'ok'}), mimetype='application/json')
    response.headers['x-slack-no-retry'] = '1'
    return response

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    import slack_helper
    return jsonify({
        'status': 'healthy',
        'version': '2.0-instant-reactions',
        'features': ['auto_bug_detection', 'instant_reactions', 'legacy_commands', 'url_validation'],
        'pending_confirmations': len(slack_helper.pending_confirmations),
        'pending_url_requests': len(slack_helper.pending_url_requests)
    })

@app.route('/debug/pending', methods=['GET'])
def debug_pending():
    """Debug endpoint to see pending requests"""
    try:
        import slack_helper
        return jsonify({
            'pending_confirmations': {
                'count': len(slack_helper.pending_confirmations),
                'messages': list(slack_helper.pending_confirmations.keys())
            },
            'pending_url_requests': {
                'count': len(slack_helper.pending_url_requests),
                'threads': list(slack_helper.pending_url_requests.keys())
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/test-parser', methods=['GET'])
def test_parser():
    """Test endpoint for message parsing"""
    try:
        from message_parser import MessageParser
        
        test_message = request.args.get('message', 'Login broken in prod environment')
        result = MessageParser.parse_message(test_message)
        
        return jsonify({
            'input': test_message,
            'parsed': result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/debug/parse-message', methods=['POST'])
def debug_parse_message():
    """Test message parsing with detailed output"""
    try:
        data = request.get_json()
        test_message = data.get('message', 'Default test message')
        
        from message_parser import MessageParser
        
        print(f"🧪 Testing message parsing for: '{test_message}'")
        
        # Parse the message
        parsed_data = MessageParser.parse_message(test_message)
        
        # Validate the result
        validation_result = {
            'has_title': bool(parsed_data.get('title')),
            'has_environment': bool(parsed_data.get('environment')),
            'has_product': bool(parsed_data.get('product')),
            'has_description': bool(parsed_data.get('description')),
            'has_urls': bool(parsed_data.get('urls')),
            'urls_structure_valid': isinstance(parsed_data.get('urls'), dict) and 
                                  'share_urls' in parsed_data.get('urls', {}) and
                                  'chat_urls' in parsed_data.get('urls', {})
        }
        
        return jsonify({
            'input_message': test_message,
            'parsed_data': parsed_data,
            'validation': validation_result,
            'all_fields_valid': all(validation_result.values()),
            'confirmation_preview': f"""🐛 Hi @user, I detected this might be a bug report:

**Title:** {parsed_data.get('title', 'N/A')}
**Environment:** {parsed_data.get('environment', 'N/A')}
**Product:** {parsed_data.get('product', 'N/A')}
**Description:** {parsed_data.get('description', '(No additional description)')}
**URLs:** {len(parsed_data.get('urls', {}).get('share_urls', []))} share, {len(parsed_data.get('urls', {}).get('chat_urls', []))} chat"""
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Clientell Jira-Slack Bot v2.0")
    print("⚡ INSTANT REACTION PROCESSING ENABLED")
    print()
    print("Features:")
    print("  ✅ Auto bug detection from channel messages")
    print("  ⚡ INSTANT emoji confirmation system")
    print("  🎯 Smart environment/product detection") 
    print("  🔗 URL validation and conversion")
    print("  🤖 Legacy command support")
    print("  👁️ Thread monitoring")
    print()
    print("Debug endpoints:")
    print("  📊 /health - Bot status")
    print("  🔍 /debug/pending - Pending requests")
    print("  🧪 /debug/test-parser?message=test - Test message parsing")
    print()
    print("Ready to process reactions instantly! 🎉")
    app.run(port=5000, debug=True)