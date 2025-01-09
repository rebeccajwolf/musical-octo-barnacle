from flask import Flask, make_response, render_template

app = Flask(__name__)

# @app.route('/')
# def home():
    # response = make_response("App is Running...")
    # return response
# @app.route("/")
# def index():
    # return render_template("index.html")
@app.route('/')
def home():
    return "App is Running..."
    
if __name__ == "__main__":
    app.config['ENV'] = 'production'
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.run()