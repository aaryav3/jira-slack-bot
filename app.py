from flask import Flask, request, jsonify, Response
import json
import slack_message_handler as slack_handler
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


@app.route('/')
def index():
    return "Hello, World"


@app.route('/slack/events', methods=['POST'])
def slack_events():
    print(f"Received request: {request.data}")
    print(f"Headers: {dict(request.headers)}")
    data = json.loads(request.data)
    # Slack sends a challenge request when you register the URL
    if 'challenge' in data:
        return jsonify({'challenge': data['challenge']})

    # We don't want to keep posting Slack messages when the response exceed three seconds.
    # Therefore, we are checking is there is any retry header in the request and ignore the retried requests.
    if 'x-slack-retry-num' not in request.headers:
        if 'event' in data and data['event']['type'] == 'message':
            if 'subtype' not in data['event']:
                slack_handler.handle_message(data["event"])

    response = Response(json.dumps({'status': 'ok'}), mimetype='application/json')
    response.headers['x-slack-no-retry'] = '1'
    return response

if __name__ == '__main__':
    app.run(port=5000)
