from flask import Flask
import threading
import time
import random

app = Flask(__name__)

def background_activity():
    """Simulate background activity without triggering container detection"""
    while True:
        # Random sleep between 30-60 seconds
        time.sleep(random.uniform(30, 60))
        
        # Minimal CPU activity
        _ = sum(i * i for i in range(100))

@app.route('/')
def home():
    return "Service is active"

def start_background_thread():
    thread = threading.Thread(target=background_activity, daemon=True)
    thread.start()

# Start background activity when the app starts
start_background_thread()

if __name__ == "__main__":
    app.config['ENV'] = 'production'
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.run()