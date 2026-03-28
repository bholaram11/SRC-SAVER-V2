import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def health():
    return "Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
