import socketio, json

s = socketio.Client(logger=False, reconnection=False)
count = 0

@s.on('connect')
def on_connect():
    print('connected')

@s.on('rover_data')
def on_rover_data(data):
    global count
    count += 1
    print(f'rover_data #{count}:', json.dumps(data, indent=2))

@s.on('connect_error')
def on_connect_error(data):
    print('connect_error:', data)

s.connect('http://localhost:5001')
try:
    s.wait()
except KeyboardInterrupt:
    s.disconnect()
