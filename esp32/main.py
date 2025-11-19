# main.py
# ESP32 MicroPython - ThingsBoard telemetry + RPC LED control example
# Hardware:
# - DHT22 data pin -> GPIO 15 (ubah sesuai wiring di Wokwi)
# - LED -> GPIO 2 (on-board LED pada banyak modul ESP32)
#
# Ganti WIFI_SSID, WIFI_PASS, THINGSBOARD_HOST, ACCESS_TOKEN sesuai milik Anda.

import time
import json
import machine
import network
from umqtt.simple import MQTTClient

# Jika menggunakan DHT22:
try:
    import dht
except Exception as e:
    # Jika dht tidak tersedia, fallback ke sensor dummy
    dht = None

# ====== CONFIG ======
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASS = "YOUR_WIFI_PASSWORD"

THINGSBOARD_HOST = "demo.thingsboard.io"   # contoh: demo.thingsboard.io atau ip/private-host
ACCESS_TOKEN = "REPLACE_WITH_DEVICE_ACCESS_TOKEN"

# Pins
DHT_PIN = 15   # data pin DHT22
LED_PIN = 2    # GPIO untuk LED

# Telemetry publish interval (detik)
PUBLISH_INTERVAL = 10

# MQTT client id
CLIENT_ID = "esp32-micropython"

# Topics for ThingsBoard
TOPIC_TELEMETRY = "v1/devices/me/telemetry"
TOPIC_RPC_REQUEST = "v1/devices/me/rpc/request/+"
TOPIC_RPC_RESPONSE_TEMPLATE = "v1/devices/me/rpc/response/{}"

# ====== SETUP ======
led = machine.Pin(LED_PIN, machine.Pin.OUT)
led.value(0)  # off

# Setup DHT sensor if available
if dht is not None:
    sensor = dht.DHT22(machine.Pin(DHT_PIN))
else:
    sensor = None

# ===== WiFi connection =====
def connect_wifi(ssid, password, timeout=15):
    wlan = network.WLAN(network.STA_IF)
    if not wlan.active():
        wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...", ssid)
        wlan.connect(ssid, password)
        t_start = time.time()
        while not wlan.isconnected():
            time.sleep(1)
            if time.time() - t_start > timeout:
                raise Exception("Could not connect to WiFi")
    print("Network config:", wlan.ifconfig())
    return wlan

# ===== MQTT callbacks =====
# We'll implement MQTT callback to receive RPC requests
last_rpc_id = None

def mqtt_callback(topic, msg):
    # topic and msg are bytes
    t = topic.decode()
    print("MQTT message:", t, msg)
    # ThingsBoard RPC topic looks like: v1/devices/me/rpc/request/<id>
    # parse id
    try:
        if t.startswith("v1/devices/me/rpc/request/"):
            rpc_id = t.split("/")[-1]
            payload = json.loads(msg.decode())
            # Expecting {"method":"setLED","params":{"value":true}} or similar
            method = payload.get("method")
            params = payload.get("params")
            if method == "setLED":
                val = False
                # support either {"value": true} or just boolean
                if isinstance(params, dict):
                    val = bool(params.get("value"))
                elif isinstance(params, bool):
                    val = params
                # set LED
                led.value(1 if val else 0)
                # respond success
                resp_topic = TOPIC_RPC_RESPONSE_TEMPLATE.format(rpc_id)
                resp = json.dumps({"success": True, "led": led.value()})
                try:
                    mqtt_client.publish(resp_topic, resp)
                except Exception as e:
                    print("Failed to publish RPC response:", e)
            else:
                # unknown method: respond error
                resp_topic = TOPIC_RPC_RESPONSE_TEMPLATE.format(rpc_id)
                resp = json.dumps({"success": False, "error": "unknown method"})
                mqtt_client.publish(resp_topic, resp)
    except Exception as e:
        print("Error handling RPC:", e)

# ===== Connect MQTT =====
def connect_mqtt():
    global mqtt_client
    mqtt_client = MQTTClient(client_id=CLIENT_ID,
                             server=THINGSBOARD_HOST,
                             user=ACCESS_TOKEN,
                             password="")  # ThingsBoard uses access token as username
    mqtt_client.set_callback(mqtt_callback)
    print("Connecting to MQTT broker", THINGSBOARD_HOST)
    mqtt_client.connect()
    print("MQTT connected")
    # subscribe to RPC requests
    mqtt_client.subscribe(TOPIC_RPC_REQUEST)
    print("Subscribed to RPC requests:", TOPIC_RPC_REQUEST)

# ===== Telemetry publish =====
def read_sensor():
    if sensor:
        try:
            sensor.measure()
            t = sensor.temperature()
            h = sensor.humidity()
            print("Sensor read T=%.2f H=%.2f" % (t, h))
            return {"temperature": round(t, 2), "humidity": round(h, 2)}
        except Exception as e:
            print("DHT read error:", e)
            return None
    else:
        # Dummy values if no sensor
        import urandom
        t = 25 + urandom.getrandbits(4) / 4.0
        h = 50 + urandom.getrandbits(5) / 2.0
        return {"temperature": round(t, 2), "humidity": round(h, 2)}

# ===== Main =====
def main():
    try:
        connect_wifi(WIFI_SSID, WIFI_PASS)
    except Exception as e:
        print("WiFi connection failed:", e)
        return

    try:
        connect_mqtt()
    except Exception as e:
        print("MQTT connection failed:", e)
        return

    last_pub = 0
    while True:
        try:
            # check for incoming messages (non-blocking with timeout 0)
            mqtt_client.check_msg()
        except Exception as e:
            print("MQTT check_msg error:", e)
            # try reconnect
            try:
                mqtt_client.disconnect()
            except:
                pass
            time.sleep(2)
            try:
                connect_mqtt()
            except Exception as e2:
                print("Reconnect failed:", e2)
                time.sleep(5)

        # publish telemetry periodically
        if time.time() - last_pub >= PUBLISH_INTERVAL:
            data = read_sensor()
            if data:
                payload = json.dumps(data)
                try:
                    mqtt_client.publish(TOPIC_TELEMETRY, payload)
                    print("Published telemetry:", payload)
                except Exception as e:
                    print("Publish error:", e)
            last_pub = time.time()
        time.sleep(0.1)

# Run
if __name__ == "__main__":
    main()
