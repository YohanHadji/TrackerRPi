from flask import Flask, render_template, request

app = Flask(__name__)

# Function to handle POST requests from buttons
def function1():
    print("Function 1 called")

def function2():
    print("Function 2 called")

@app.route('/')
def index():
    return render_template('oldIndex.html')

@app.route('/button1', methods=['POST'])
def button1():
    function1()
    return '', 204

@app.route('/button2', methods=['POST'])
def button2():
    function2()
    return '', 204

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)