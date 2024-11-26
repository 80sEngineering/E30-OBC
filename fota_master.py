from FOTA import access_point, dns, server
from FOTA.template import render_template
from FOTA.ota import OTAUpdater
import json
import machine
import os
import utime
import _thread
import network

def machine_reset():
    utime.sleep(1)
    print("Resetting...")
    machine.reset()

def setup_mode():
    print("Entering setup mode...")
    
    AP_NAME = "E30_OBC"
    AP_DOMAIN = "obc-80s.engineering"
    AP_TEMPLATE_PATH = "FOTA/ap_templates"
    APP_TEMPLATE_PATH = "FOTA/app_templates"

    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    networks = wlan.scan()
    
    found_wifi_networks = {}
    
    for n in networks:
        ssid = n[0].decode().strip('\x00')
        if len(ssid) > 0:
            rssi = n[3]
            if ssid in found_wifi_networks:
                if found_wifi_networks[ssid] < rssi:
                    found_wifi_networks[ssid] = rssi
            else:
                found_wifi_networks[ssid] = rssi

    wifi_networks_by_strength = sorted(found_wifi_networks.items(), key = lambda x:x[1], reverse = True)
    
    print(wifi_networks_by_strength)
    
    def ap_index(request):
        if request.headers.get("host").lower() != AP_DOMAIN.lower():
            return render_template(f"{AP_TEMPLATE_PATH}/redirect.html", domain = AP_DOMAIN.lower())

        return render_template(f"{AP_TEMPLATE_PATH}/index.html", wifis = wifi_networks_by_strength)


    def ap_configure(request):
        print("Saving wifi credentials...")

        with open('wifi.json', "w") as f:
            json.dump(request.form, f)
            f.close()

        # Reboot from new thread after we have responded to the user.
        _thread.start_new_thread(machine_reset, ())
        return render_template(f"{AP_TEMPLATE_PATH}/configured.html", ssid = request.form["ssid"])
        
    def ap_catch_all(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template(f"{AP_TEMPLATE_PATH}/redirect.html", domain = AP_DOMAIN)

        return "Not found.", 404

    server.add_route("/", handler = ap_index, methods = ["GET"])
    server.add_route("/configure", handler = ap_configure, methods = ["POST"])
    server.set_callback(ap_catch_all)

    ap = access_point(AP_NAME)
    ip = ap.ifconfig()[0]
    dns.run_catchall(ip)


def application_mode():
    print("Entering application mode.")
    firmware_url = "https://raw.githubusercontent.com/80sEngineering/MeshCataloger/"
    ota_updater = OTAUpdater(firmware_url, "Viewer.py")
    ota_updater.download_and_install_update_if_available()
    
    
def old_application_mode():
    print("Entering application mode.")
    AP_TEMPLATE_PATH = "FOTA/ap_templates"
    APP_TEMPLATE_PATH = "FOTA/app_templates"

    onboard_led = machine.Pin("LED", machine.Pin.OUT)

    def app_index(request):
        return render_template(f"{APP_TEMPLATE_PATH}/index.html")

    def app_toggle_led(request):
        onboard_led.toggle()
        return "OK"
    
    def app_get_temperature(request):
        sensor_temp = machine.ADC(4)
        reading = sensor_temp.read_u16() * (3.3 / (65535))
        temperature = 27 - (reading - 0.706)/0.001721
        return f"{round(temperature, 1)}"
    
    def app_reset(request):
        # Deleting the WIFI configuration file will cause the device to reboot as
        # the access point and request new configuration.
        os.remove("wifi.json")
        # Reboot from new thread after we have responded to the user.
        _thread.start_new_thread(machine_reset, ())
        return render_template(f"{APP_TEMPLATE_PATH}/reset.html", access_point_ssid = AP_NAME)

    def app_catch_all(request):
        return "Not found.", 404

    server.add_route("/", handler = app_index, methods = ["GET"])
    server.add_route("/toggle", handler = app_toggle_led, methods = ["GET"])
    server.add_route("/temperature", handler = app_get_temperature, methods = ["GET"])
    server.add_route("/reset", handler = app_reset, methods = ["GET"])
    # Add other routes for your application...
    server.set_callback(app_catch_all)

