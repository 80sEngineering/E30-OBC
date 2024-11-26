import time
from math import log
import ht16k33_driver
from GPS_parser import GPS_handler
from button import Button
from imu import MPU6050
from dictionnary import Dictionnary
from unit import Unit
from machine import I2C, Pin, RTC, ADC, lightsleep, WDT, PWM
from timer import Timer, LapTimer
import ujson as json
from memory import access_data
import fota_master
from FOTA import connect_to_wifi, is_connected_to_wifi, server
from FOTA.ota import OTAUpdater
import os
import logging


class OBC:
    def __init__(self):
        self.pwr_pin = Pin(4, Pin.OUT)
        self.pwr_pin.high()
        self.powered = True
        
        self.button1 = Button(6, 1, self.function_manager)
        self.button2 = Button(7, 2, self.function_manager)
        self.button3 = Button(8, 3, self.function_manager)
        self.button4 = Button(9, 4, self.function_manager)
        self.button5 = Button(10, 5, self.function_manager)
        self.button6 = Button(11, 6, self.function_manager)
        self.button7 = Button(12, 7, self.function_manager)
        self.button8 = Button(13, 8, self.function_manager)
        self.button9 = Button(14, 9, self.set_reset)
        self.button10 = Button(18, 10, self.digit_manager)
        self.button11 = Button(19, 11, self.digit_manager)
        self.button12 = Button(20, 12, self.digit_manager)
        self.button13 = Button(21, 13, self.digit_manager)
        

        self.digit_pressed = 0
        backlight = Pin(15, Pin.OUT)
        self.backlight_pwm = PWM(backlight)
        self.backlight_pwm.freq(1000)
        self.backlight_brightness = access_data('backlight_brightness')
        self.led = Pin(25, Pin.OUT)
        self.led.high()
        self.light_optocoupler = Pin(22, Pin.IN)
        self.light_optocoupler.irq(handler=self.set_backlight, trigger = Pin.IRQ_RISING|Pin.IRQ_FALLING)
        self.temp_power = Pin(5, Pin.OUT)
        self.temp_adc = ADC(2)
        self.pressure_adc = ADC(1)
        self.battery_adc = ADC(Pin(26, Pin.IN))
        increased_adc_resolution = Pin(23,Pin.OUT)
        increased_adc_resolution.high()
        self.refresh_rate_adjuster = {'timestamp':None,'values':[]}
        self.init_i2c()
        self.rtc = RTC()
        self.rtc.datetime(access_data('current_time'))

        self.timer = Timer()
        self.laptimer = LapTimer()
        self.acceleration_timer = Timer()

        self.gps = GPS_handler()
        self.speed_limit = 0
        self.speed_limit_is_active = False
        self.max_temperature = 0
        self.temperature_limit_is_active = False
        
        language = access_data("language")
        self.words = Dictionnary(language).words
        unit = access_data("unit")
        self.unit = Unit(unit)
        self.setting_index = 0
        self.displayed_function = self.hour
        self.last_displayed_function = None
        self.last_use = time.ticks_ms()
        self.can_switch_function = True
        self.priority_counter = 0
        self.priority_interval = [1,20,40]
        #self.watchdog = WDT(timeout=5000)
        logging.info('> System initialized')
        self.loop()
    
    def init_i2c(self):
        i2c = I2C(id=1, sda=Pin(2), scl=Pin(3), freq = 9600)
        self.display = ht16k33_driver.Seg14x4(i2c)
        self.display.brightness(access_data('display_brightness'))
        self.mpu = MPU6050(i2c)
        
        
    def function_manager(self, button_id, long_press):
        self.last_use = time.ticks_ms()
        self.digit_pressed = 0
        if not self.powered:
            self.power_handler()
        if self.can_switch_function:
            if button_id == 1:
                if self.displayed_function.__name__ == 'hour':
                    self.displayed_function = self.date
                else:
                    self.displayed_function = self.hour

            elif button_id == 2:
                self.displayed_function = self.speed


            elif button_id == 3:
                self.displayed_function = self.acceleration
                
                
            elif button_id == 4:
                self.displayed_function = self.lap_timer
                

            elif button_id == 5:
                self.displayed_function = self.odometer


            elif button_id == 6:
                if self.displayed_function.__name__ == 'timer_function':
                    self.timer.is_displayed = True
                    if self.timer.lap_start != 0:
                        if self.timer.is_running:
                            self.timer.lap()
                        else:
                            self.timer.reset()
                else:
                    self.displayed_function = self.timer_function
                    self.timer.is_displayed = False
                    
                

            elif button_id == 7:
                if access_data('sensors_nb') == 3 and not self.displayed_function.__name__ in ['pressure','temperature']:
                    self.displayed_function = self.pressure
                    
                elif access_data('sensors_nb')>=2 and not self.displayed_function.__name__ == 'temperature':
                    self.displayed_function = self.temperature
                    self.refresh_rate_adjuster['values'].clear()
                    
                elif self.displayed_function.__name__ == 'temperature' or access_data('sensors_nb')==1:
                    self.displayed_function = self.voltage
                
                

            elif button_id == 8:
                if self.displayed_function.__name__ == 'g_sensor':
                    self.displayed_function = self.heading
                elif self.displayed_function.__name__ == 'heading':
                    self.displayed_function = self.altitude
                else:
                    self.displayed_function = self.g_sensor
        else:
            logging.debug("Switching function not allowed")
            
        logging.info(f"> Displayed function: {self.displayed_function.__name__}")

    def digit_manager(self, button_id, long_press):
        self.last_use = time.ticks_ms()
        if self.displayed_function.__name__ in ('set_hour', 'set_date', 'set_year', 'set_limit', 'set_odometer_thousands','set_odometer_hundreds', 'set_max_temperature','set_setting', 'set_language','set_clock_format', 'set_unit','set_display_brightness','set_sensors_nb','set_auto_off','set_backlight_brightness','set_gsensor_error'):
            if not long_press:
                digit_map = {10: 1000, 11: 100, 12: 10, 13:1}
                self.digit_pressed = digit_map.get(button_id)
            else:
                digit_map = {10: -1000, 11: -100, 12: -10,13:-1}
                self.digit_pressed = digit_map.get(button_id)
            logging.info(f"> Pressed digit: {self.digit_pressed}")
        else:
            if (button_id == 10 and not self.button12.pin.value()) or (button_id == 12 and not self.button10.pin.value()):
                self.displayed_function = self.set_setting
                self.display.fill()
                self.display.show()
                time.sleep_ms(2000)

    def set_reset(self, button_id, long_press):
        self.last_use = time.ticks_ms()
        self.digit_pressed = 0
        if not long_press:
            if not self.powered:
                self.power_handler()
                
            elif self.displayed_function.__name__ == 'hour':
                self.displayed_function = self.set_hour
                self.display.blink_rate(1)
                self.can_switch_function = False

            elif self.displayed_function.__name__ == 'set_hour':
                self.displayed_function = self.hour
                self.display.blink_rate(0)
                self.can_switch_function = True

            elif self.displayed_function.__name__ == 'date':
                self.displayed_function = self.set_year
                self.display.blink_rate(1)
                self.can_switch_function = False

            elif self.displayed_function.__name__ == 'set_year':
                self.displayed_function = self.set_date

            elif self.displayed_function.__name__ == 'set_date':
                self.displayed_function = self.date
                self.display.blink_rate(0)
                self.can_switch_function = True

            elif self.displayed_function.__name__ == 'timer_function':
                if not self.timer.is_running:
                    self.timer.start()
                else:
                    self.timer.stop()

            elif self.displayed_function.__name__ == 'lap_timer':
                if self.laptimer.is_running:
                    self.laptimer.end()
                elif self.gps.parsed.fix_type:
                    self.laptimer.reset_laptimer()
                    self.laptimer.start()
            
            elif self.displayed_function.__name__ == 'acceleration':
                if self.acceleration_timer.start_time is not None:
                    self.acceleration_timer.reset()
                
            
            elif self.displayed_function.__name__ == 'speed':
                self.displayed_function = self.set_limit
                self.can_switch_function = False
                self.display.blink_rate(1)
                
            
            elif self.displayed_function.__name__ == 'set_limit':
                self.display.blink_rate(0)
                self.displayed_function = self.speed
                self.speed_limit_is_active = not self.speed_limit_is_active
                self.can_switch_function = True

            elif self.displayed_function.__name__ == 'check_for_overspeed':
                self.speed_limit_is_active = False
                self.display.blink_rate(0)
                self.can_switch_function = True
                
                
            elif self.displayed_function.__name__ == 'odometer':
                self.display.blink_rate(0)
                self.displayed_function = self.set_odometer_thousands
                self.can_switch_function = False

            elif self.displayed_function.__name__ == 'set_odometer_thousands':
                self.display.blink_rate(0)
                self.displayed_function = self.set_odometer_hundreds
                
                
            elif self.displayed_function.__name__ == 'set_odometer_hundreds':
                self.display.blink_rate(0)
                self.displayed_function = self.odometer
                self.can_switch_function = True
            
            elif self.displayed_function.__name__ == 'temperature':
                self.display.blink_rate(1)
                self.displayed_function = self.set_max_temperature
                self.can_switch_function = False

            elif self.displayed_function.__name__ == 'set_max_temperature':
                self.display.blink_rate(0)
                self.displayed_function = self.temperature
                self.temperature_limit_is_active = not self.temperature_limit_is_active
                self.can_switch_function = True
            
            elif self.displayed_function.__name__ == 'check_for_overheat':
                self.display.blink_rate(0)
                self.temperature_limit_is_active = False
                self.can_switch_function = True
            
            elif self.displayed_function.__name__ == 'set_setting':
                setting_functions = [self.set_language,self.set_clock_format,self.set_unit,self.sw_update,self.set_display_brightness,self.set_sensors_nb,self.set_auto_off,self.set_backlight_brightness,self.set_gsensor_error]
                try:
                    self.displayed_function = setting_functions[self.setting_index]
                except IndexError:
                    pass
               
            elif self.displayed_function.__name__ == 'sw_update':
                fota_master.machine_reset()
                
            elif self.displayed_function.__name__ in ['set_language','set_clock_format','set_unit','set_display_brightness','set_sensors_nb','set_auto_off','set_backlight_brightness','set_gsensor_error']:
                self.displayed_function = self.set_setting
            
            logging.info(f"> Displayed function: {self.displayed_function.__name__}")
       
        else:
            if self.can_switch_function:
                self.power_handler()
                
        
    def show(self, text):
        if self.powered:
            self.display.clear()
            self.display.put_text(text)
            self.display.show()

    def show_function_name(self, button):
        now = time.ticks_ms()
        if time.ticks_diff(now, button.current_press['release']) < 700:
            return True
        else:
            return False


    def hour(self):
        if self.show_function_name(self.button1):
            self.show(self.words['HOUR'])
        else:
            current_time = self.rtc.datetime()
            self.show_hour(current_time)

    def set_hour(self):
        current_time = self.rtc.datetime()
        year, month, day, week_day, hour, minute, second, ms = current_time[0], current_time[1], current_time[2], \
            current_time[3], current_time[4], current_time[5], 0, current_time[7]
        digit_mapping = {
            1000: (10, 0),
            100: (1, 0),
            10: (0, 10),
            1: (0, 1),
            -1: (0, -1),
            -10: (0, -10),
            -100: (-1, 0),
            -1000: (-10, 0)
        }

        if self.digit_pressed in digit_mapping:
            hour_change, minute_change = digit_mapping[self.digit_pressed]
            hour += hour_change
            minute += minute_change
            hour = hour % 24
            minute = minute % 60
            current_time = (year, month, day, week_day, hour, minute, second, ms)
            self.rtc.datetime(current_time)
            self.digit_pressed = 0
        self.show_hour(current_time)

    def show_hour(self, time_to_show):
        minute = "{:02d}".format(time_to_show[5])
        second = time_to_show[6]
        if access_data('clock_format') == 24:
            hour = "{:02d}".format(time_to_show[4])
            if second % 2 == 0:
                self.show(' ' + hour + '.' + minute)
            else:
                self.show(' ' + hour + minute)
        else:
            hour = time_to_show[4]
            hour_suffix = 'AM' if hour < 12 else 'PM'
            hour = "{:02d}".format(hour % 12)
            if hour == "00":
                hour = "12"
            if second % 2 == 0:
                self.show(hour + '.' + minute + hour_suffix)
            else:
                self.show(hour + minute + hour_suffix)
                

    def date(self):
        if self.show_function_name(self.button1):
            self.show(self.words['DATE'])
        else:
            current_time = self.rtc.datetime()
            self.show_date(current_time, display_year=False)

    def set_year(self):
        current_time = self.rtc.datetime()
        year, month, day, week_day, hour, minute, second, ms = current_time[0], current_time[1], current_time[2], \
            current_time[3], current_time[4], current_time[5], 0, current_time[7]
        digit_mapping = {
            10: 10,
            1: 1,
            -1: -1,
            -10: -10
        }

        if self.digit_pressed in digit_mapping:
            year += digit_mapping[self.digit_pressed]
            if year > 2100 or year < 1986:
                year = 2023
            current_time = (year, month, day, week_day, hour, minute, second, ms)
            self.rtc.datetime(current_time)
            self.digit_pressed = 0
        self.show_date(current_time, display_year=True)

    def set_date(self):
        current_time = self.rtc.datetime()
        year, month, day, week_day, hour, minute, second, ms = current_time[0], current_time[1], current_time[2], \
            current_time[3], current_time[4], current_time[5], 0, current_time[7]
        digit_mapping = {
            1000: (10, 0),
            100: (1, 0),
            10: (0, 10),
            1: (0, 1),
            -1: (0, -1),
            -10: (0, -10),
            -100: (-1, 0),
            -1000: (-10, 0)
        }

        if self.digit_pressed in digit_mapping:
            day_change, month_change = digit_mapping[self.digit_pressed]
            day += day_change
            month += month_change
            if day > 31 or day < 1:
                day = 1
            if month > 12 or month < 1:
                month = 1
            current_time = (year, month, day, week_day, hour, minute, second, ms)
            self.rtc.datetime(current_time)
            self.digit_pressed = 0
        self.show_date(current_time, display_year=False)

    def show_date(self, date_to_show, display_year=False):
        if display_year:
            self.show(str(date_to_show[0]))
        else:
            months = self.words['months']
            day = date_to_show[2]
            month = date_to_show[1]
            month_str = months[month - 1]

            if day < 10:
                day_str = '0' + str(day)
            else:
                day_str = str(day)

            self.show(day_str + ' ' + month_str)
            
            
    def speed(self):
        if self.show_function_name(self.button2):
            self.show(self.words['SPEED'])
        elif self.show_function_name(self.button9):
            if self.speed_limit_is_active:
                self.show('  ON  ')
            else:
                self.show(' OFF  ')
        else:
            if self.gps.has_fix():
                speed = self.gps.parsed.speed[self.unit.speed_index]
                self.show(str(int(speed))+self.unit.speed_acronym)
            else:
                self.show(self.words['SIGNAL'])
                
                
    def set_limit(self):
        if self.show_function_name(self.button9):
            self.show(self.words['LIMIT'])
        else:
            digit_mapping = {
                100: (100),
                10: (10),
                1: (1),
                -1: (-1),
                -10: (-10),
                -100: (-100)
            }

            if self.digit_pressed in digit_mapping:
                delta = digit_mapping[self.digit_pressed]
                if self.digit_pressed in [-1, -10, -100] and self.speed_limit % 10 != 0:
                    self.speed_limit -= self.speed_limit % 100 % 10
                self.speed_limit += delta
                if self.speed_limit > 400 or self.speed_limit < 0:
                    self.speed_limit = 0
                self.digit_pressed = 0
            self.show(str(self.speed_limit) + self.unit.speed_acronym)


    def check_for_overspeed(self):
        if not self.displayed_function.__name__ == "set_limit" and self.can_switch_function:
            if self.gps.has_fix():
                current_speed = self.gps.parsed.speed[self.unit.speed_index]
                gone_overspeed = False
                switching = True
                if current_speed > self.speed_limit and self.speed_limit_is_active:
                    logging.car("> Entering overspeed at {current_speed}")
                while current_speed > self.speed_limit and self.speed_limit_is_active:
                    self.watchdog.feed()
                    self.displayed_function = self.check_for_overspeed
                    gone_overspeed = True
                    self.can_switch_function = False
                    self.display.blink_rate(1)
                    switching = not switching
                    if switching:
                        self.show(self.words['LIMIT'])
                    else:
                        self.show(str(int(current_speed)) + self.unit.speed_acronym)
                    start = time.ticks_ms()
                    while time.ticks_diff(time.ticks_ms(),start) < 1000:
                        pass
                    self.gps.get_GPS_data()
                    current_speed = self.gps.parsed.speed[self.unit.speed_index]
                if gone_overspeed:
                    self.display.blink_rate(0)
                    self.can_switch_function = True
                    self.displayed_function = self.speed
    
    def acceleration(self):
        if self.show_function_name(self.button3):
            self.show(self.words['ACCEL'])
        else:
            if self.gps.has_fix():
                if not self.acceleration_timer.is_running and self.acceleration_timer.start_time == None and not self.acceleration_timer.show_lap_time():
                    acceleration = self.mpu.accel
                    self.display.blink_rate(0)
                    self.can_switch_function = True
                    if self.gps.parsed.speed[2] > 2:
                        self.show(self.words['STOP'])
                    else:
                        self.show(self.words['READY'])
                    
                    if acceleration.x > 0.5 and self.gps.parsed.speed[2] < 2:
                        self.acceleration_timer.start()
                else:
                    speed_target = 100 #kmh
                    if self.gps.parsed.speed[2] >= speed_target and self.acceleration_timer.is_running:
                        self.acceleration_timer.display_end_time = time.ticks_add(time.ticks_ms(),4000)
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        time_to_100 = self.acceleration_timer.parse_time(self.acceleration_timer.get_elapsed_time())
                        logging.car(f"> {speed_target}kmh reached in {time_to_100}.")
                        self.acceleration_timer.reset()
                    if self.acceleration_timer.show_lap_time():
                        pass
                    else:
                        time_to_show = self.acceleration_timer.get_elapsed_time()
                        self.show(self.acceleration_timer.parse_time(time_to_show))
                    
            else:
                self.show(self.words['SIGNAL'])


    def lap_timer(self):
        if self.show_function_name(self.button4):
            self.show(self.words['LAP'])
        else:  
            if self.gps.has_fix():
                if self.laptimer.is_running:
                    if self.laptimer.start_position is None:
                        self.laptimer.set_start_position(self.gps.parsed)                          
                    if self.gps.parsed.longitude != self.gps.previous_place['longitude'] and self.gps.parsed.latitude != self.gps.previous_place['latitude']:
                        self.laptimer.check_for_completed_lap(self.gps.parsed)
                    
                    if self.laptimer.show_lap_time():
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        timer_str = self.laptimer.parse_time(self.laptimer.lap_time)
                        
                    elif self.laptimer.show_delay():
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        if self.laptimer.delay > 0:
                            timer_str = str(self.laptimer.parse_time(self.laptimer.delay, '+'))
                        else:
                            timer_str = str(self.laptimer.parse_time(self.laptimer.delay, '-'))
                        
                    elif self.laptimer.show_laps():
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        if self.laptimer.number_of_lap < 10:
                            timer_str = str(self.laptimer.number_of_lap - 1)+'  LAP'
                        else:
                            timer_str = str(self.laptimer.number_of_lap - 1)+' LAP'
                    else:
                        self.can_switch_function = True
                        self.display.blink_rate(0)
                        time_to_show = self.laptimer.get_elapsed_lap_time()
                        timer_str = self.laptimer.parse_time(time_to_show)
                    self.show(str(timer_str))
                else:
                    if self.laptimer.show_laps():
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        if self.laptimer.number_of_lap < 10:
                            timer_str = 'LAP  '+str(self.laptimer.number_of_lap)
                        else:
                            timer_str = 'LAP '+str(self.laptimer.number_of_lap)
                        
                    elif self.laptimer.show_lap_time():
                        self.display.blink_rate(5)
                        self.can_switch_function = False
                        timer_str = self.laptimer.parse_time(self.laptimer.fastest_lap[0])
                    else:
                        self.display.blink_rate(0)
                        self.can_switch_function = True
                        timer_str = self.words['READY']  
                    self.show(str(timer_str))
            else:
                self.show(self.words['SIGNAL'])


    def odometer(self):
        if self.show_function_name(self.button5):
            self.show(self.words['ODO'])
        else:
            value = access_data('odometer')
            value = round(value,1)
            if value%1!=0:
                value_str = "{:>7}".format(value)
            elif value < 100000:
                value_str = "{:>6}".format(value)
            self.show(str(value_str))
            
            
    def set_odometer(self, unit):
        odometer_value = int(access_data('odometer'))
        if unit == 'k':
            digit_mapping = {100: 100000, 10: 10000, 1: 1000, -1: -1000, -10: -10000, -100: -100000}
        else:
            digit_mapping = {1000: 1000, 100: 100, 10: 10, 1: 1, -1: -1, -10: -10, -100: -100, -1000: -1000}
        if self.digit_pressed in digit_mapping:
            odometer_value += digit_mapping.get(self.digit_pressed, 0)
            if odometer_value < 0:
                odometer_value = 0
            elif odometer_value > 999999:
                odometer_value = 0
            access_data("odometer", odometer_value)
            self.digit_pressed = 0      
            
    def set_odometer_thousands(self):
        odometer_value = int(access_data('odometer'))
        odometer_str = str(odometer_value)
        odometer_str = self.display.zeros_before_number(odometer_str)
        now = time.ticks_ms()
        time_to_adjuster = time.ticks_diff(self.refresh_rate_adjuster['timestamp'],now)
        if time_to_adjuster < 300:
            odometer_str = odometer_str[-3:]
            odometer_str = "{:>6}".format(odometer_str)
            if time_to_adjuster < 50:
                self.refresh_rate_adjuster['timestamp'] = time.ticks_add(now, 600)        
        
        self.show(odometer_str)
        self.set_odometer('k')
                
    def set_odometer_hundreds(self):
        odometer_value = int(access_data('odometer'))
        odometer_str = str(odometer_value)
        odometer_str = self.display.zeros_before_number(odometer_str)
        now = time.ticks_ms()
        time_to_adjuster = time.ticks_diff(self.refresh_rate_adjuster['timestamp'],now)
        if time_to_adjuster < 300:
            odometer_str = odometer_str[:-3]
            
            if time_to_adjuster<50:
                self.refresh_rate_adjuster['timestamp'] = time.ticks_add(now, 600)
        self.show(odometer_str)
        self.set_odometer('h')
        
        
    def timer_function(self):
        if self.show_function_name(self.button6) and not self.timer.is_displayed:
            self.show(self.words['TIMER'])
        else:
            if not self.timer.show_lap_time():
                self.can_switch_function = True
                self.display.blink_rate(0)
                time_to_show = self.timer.get_elapsed_time()
            else:
                self.can_switch_function = False
                self.display.blink_rate(5)
                time_to_show = self.timer.lap_time
            
            timer_str = self.timer.parse_time(time_to_show)
            self.show(timer_str)
    
    def get_pressure(self):
        conversion_factor = 3.3 / 65535
        read_voltage = self.pressure_adc.read_u16() * conversion_factor
        real_voltage = abs(read_voltage*1.5)
        psi_pressure = (real_voltage-0.25)*150/4
        if psi_pressure < 4:
            psi_pressure = 0
        bar_pressure = round(psi_pressure * 0.068948,1)
        if self.unit.system == 'METRIC':
            return bar_pressure
        elif self.unit.system == 'IMPERI.':
            return round(psi_pressure,1)
        
        
    def pressure(self):
        if self.show_function_name(self.button7):
            self.show(self.words['OIL'])
        else:
            if time.ticks_diff(time.ticks_ms(), self.refresh_rate_adjuster['timestamp']) > 300:
                pressure = self.get_pressure()
                self.show(str(pressure) + ' ' + self.unit.pressure_acronym)
                self.refresh_rate_adjuster['timestamp'] = time.ticks_ms()
            
    def temperature_formatter(self, temperature):
        if temperature < -50:
            return 'NODATA'
        temperature_str = f"{temperature: 4.0f}{self.unit.temperature_acronym}"
        return temperature_str if temperature < 100 else ' ' + temperature_str
        
        
    def get_temperature(self,string):
        self.temp_power.high()
        conversion_factor = 3.3 / 65535
        voltage = self.temp_adc.read_u16() * conversion_factor
        self.temp_power.low()
        RNTC = 39600 * (( 1 / voltage ) - ( 10/33))
        A = 1.291780732 * 10 ** -3
        B = 2.612878251 * 10 ** -4
        C = 1.568295903 * 10 ** -7
        try:
            temperature = 1 /( A + B * log(RNTC) + C *(log(RNTC))**3)
        except:
            logging.exception(f"> Error while computing temperature. RNTC value: {RNTC}")
            temperature = 222
        celsius_temperature = temperature - 273.15
        fahrenheit_temperature = (celsius_temperature *  1.8) + 32
        if self.unit.system == 'METRIC':
            temperature_to_show = celsius_temperature
        elif self.unit.system == 'IMPERI.':
            temperature_to_show = fahrenheit_temperature
        if not string:
            return temperature_to_show            
        else:
            return self.temperature_formatter(temperature_to_show)
    
    
    def temperature(self):
        if self.show_function_name(self.button7):
            self.show(self.words['TEMP'])
        elif self.show_function_name(self.button9):
            if self.temperature_limit_is_active:
                self.show('  ON  ')
            else:
                self.show(' OFF  ')
        else:
            try:
                self.refresh_rate_adjuster['values'].append(self.get_temperature(False))
            except MemoryError:
                logging.exception(f"> MemoryError in self.refresh_rate_updater. Array lenght: {len(self.refresh_rate_adjuster['values'])}") 
            
            if time.ticks_diff(time.ticks_ms(), self.refresh_rate_adjuster['timestamp']) > 1000:
                if len(self.refresh_rate_adjuster['values']) > 2:
                    rounded_temperature = sum(self.refresh_rate_adjuster['values']) / len(self.refresh_rate_adjuster['values'])
                    self.show(self.temperature_formatter(rounded_temperature))
                    self.refresh_rate_adjuster['values'].clear()
                else:
                    self.show(self.get_temperature(True))
                self.refresh_rate_adjuster['timestamp'] = time.ticks_ms()
            
                    
    
    def set_max_temperature(self):
        if self.show_function_name(self.button9):
            self.show(' MAX.')
        else:
            digit_mapping = {100: 100, 10: 10, 1: 1, -1: -1, -10: -10, -100: -100, -1000: -1000}
            if self.digit_pressed in digit_mapping:
                self.max_temperature += digit_mapping[self.digit_pressed]
                if self.max_temperature > 150 or self.max_temperature < 0:
                    self.max_temperature = 0
                self.digit_pressed = 0
            max_temperature_str = self.temperature_formatter(self.max_temperature)
            self.show(max_temperature_str)
    
    def check_for_overheat(self):
        if not self.displayed_function.__name__ == "set_max_temperature" and self.can_switch_function:
            temperature = int(self.get_temperature(False))
            switching = True
            gone_overheat = False
            if temperature > self.max_temperature and self.temperature_limit_is_active:
                logging.car(f"> Oil overheating! Temperature: {temperature}")
            while temperature > self.max_temperature and self.temperature_limit_is_active:
                self.watchdog.feed()
                self.displayed_function = self.check_for_overheat
                self.can_switch_function = False
                gone_overheat = True
                self.display.blink_rate(1)
                if switching: 
                    self.show(self.words['TEMP'])
                else:
                    if time.ticks_diff(time.ticks_ms(), self.refresh_rate_adjuster['timestamp']) > 1000:
                        self.show(self.get_temperature(True))
                        self.refresh_rate_adjuster['timestamp'] = time.ticks_ms()
                switching = not switching
                start = time.ticks_ms()
                while time.ticks_diff(time.ticks_ms(), start) < 1000:
                    pass
                temperature = int(self.get_temperature(False))
            if gone_overheat:
                logging.car("> Stopped overheating.")
                self.display.blink_rate(0)
                self.can_switch_function = True
                self.displayed_function = self.temperature
    
    def get_voltage(self):
        adc_value = self.battery_adc.read_u16() - 300
        voltage = 3.3 * adc_value / 65535 
        battery_voltage = voltage * (12000 + 3300) / 3300
        return battery_voltage
    
    def voltage(self):
        if self.show_function_name(self.button7):
            self.show(self.words['VOLT'])
        else:
            if time.ticks_diff(time.ticks_ms(), self.refresh_rate_adjuster['timestamp']) > 1000:
                self.refresh_rate_adjuster['timestamp'] = time.ticks_ms()
                battery_voltage_str = "{:.1f}".format(self.get_voltage())
                self.show(' ' + battery_voltage_str + 'V')

    def altitude(self):
        if self.show_function_name(self.button8):
            self.show(self.words['ALT'])
        else:
            if self.gps.has_fix():
                if self.unit.system == 'METRIC':
                    altitude = self.gps.parsed.altitude
                elif self.unit.system == 'IMPERI.':
                    altitude = self.gps.parsed.altitude * 3.28084
                self.show(str(int(altitude)) + self.unit.altitude_acronym)
            else:
                self.show(self.words['SIGNAL'])

    def heading(self):
        if self.show_function_name(self.button8):
            self.show(self.words['HDG'])
        else:
            if self.gps.has_fix():
                compass_direction = self.gps.parsed.compass_direction()
                heading = self.gps.parsed.course
                self.show(str(int(heading)) + compass_direction)
            else:
                self.show(self.words['SIGNAL'])

    def g_sensor(self):
        if self.show_function_name(self.button8):
            self.show(self.words['G SENS'])
        else:
            if time.ticks_diff(time.ticks_ms(), self.refresh_rate_adjuster['timestamp']) > 200:
                g_error = access_data('g_error')
                self.refresh_rate_adjuster['timestamp'] = time.ticks_ms()
                acceleration = self.mpu.accel
                g_vector = ((acceleration.x + (g_error[0]/10)) ** 2 + (acceleration.z + (g_error[1]/10)) **2) ** 0.5
                self.show(' ' + str(round(g_vector, 1)) + 'G')
    
    def set_setting(self):
        digit_mapping = {1:1, -1:-1}
        if self.digit_pressed in digit_mapping:
            self.setting_index+=digit_mapping[self.digit_pressed]
            if self.setting_index>9 or self.setting_index < 0:
                self.setting_index = 0
            self.digit_pressed = 0
        self.show('SET  '+str(self.setting_index))
    
    def set_language(self):
        if self.show_function_name(self.button9):
            self.show('LANGUA.')
        else:
            language = access_data('language')
            possible_languages = ['EN','FR','DE']
            index = possible_languages.index(language)
            digit_mapping = {1:1, -1:-1}
            if self.digit_pressed in digit_mapping:
                index+= digit_mapping[self.digit_pressed]
                if index >= len(possible_languages) or index < 0:
                    index = 0
                access_data('language',possible_languages[index])
                self.words = Dictionnary(possible_languages[index]).words
                self.unit.update()
                self.digit_pressed = 0
            self.show(access_data('language'))
    
    def set_clock_format(self):
        if self.show_function_name(self.button9):
            self.show('12/24')
        else:
            clock_format = access_data('clock_format')
            if clock_format == 24:
                self.show('24H')
            else:
                self.show('12AMPM')
            if self.digit_pressed in [-1,1]:
                clock_format = 12 if clock_format == 24 else 24
                access_data('clock_format',clock_format)
                self.digit_pressed = 0
            
    def set_unit(self):
        if self.show_function_name(self.button9):
            self.show('UNIT')
        else:
            unit = access_data('unit')
            possible_units = ['METRIC','IMPERI.']
            index = possible_units.index(unit)
            digit_mapping = {1:1, -1:-1}
            if self.digit_pressed in digit_mapping:
                index+=digit_mapping[self.digit_pressed]
                if index >= 2 or index < 0:
                    index = 0
                access_data('unit', possible_units[index])
                self.unit.system = possible_units[index]
                self.unit.update()
                self.digit_pressed = 0
            self.show(access_data('unit'))
    
    def sw_update(self):
        if self.show_function_name(self.button9):
            self.show('UPDATE')
        else:
            self.show(' WIFI ')
            self.can_switch_function = False
            try:
                os.stat("wifi.json")
                with open("wifi.json", 'r') as f:
                    wifi_current_attempt = 1
                    wifi_credentials = json.load(f)
                    
                while (wifi_current_attempt < 3):
                    try:
                        ip_address = connect_to_wifi(wifi_credentials["ssid"], wifi_credentials["password"])
                    except:
                        logging.exception('> Exception occured while connecting to wifi.')
                    if is_connected_to_wifi():
                        logging.debug(f"> Connected to wifi, IP address {ip_address}")
                        self.show('CNNCTD')
                        time.sleep(2)
                        self.show(wifi_credentials["ssid"][:6])
                        time.sleep(2)
                        break
                    else:
                        wifi_current_attempt += 1
            
            except OSError:
                logging.debug("> OSError occured as wifi.json doesn't exist")
                with open('wifi.json', 'w') as f:
                    json.dump({}, f)
                
            if is_connected_to_wifi():
                logging.debug("> Entering update mode.")
                firmware_url = "https://raw.githubusercontent.com/80sEngineering/MeshCataloger/"
                ota_updater = OTAUpdater(firmware_url, "Viewer.py")
                ota_updater.check_for_updates()
                if ota_updater.newer_version_available:
                    self.show('NEW'+'{:>3}'.format('V'+str(ota_updater.latest_version)))
                    time.sleep(2)
                    self.show('UPDATE')
                    time.sleep(2)
                    self.display.clear()
                    self.display.show()
                    if ota_updater.fetch_latest_code():
                        ota_updater.update_no_reset() 
                        ota_updater.update_and_reset()
                else:
                    logging.debug("> No new updates available.")
                    self.show('LATEST')
                    time.sleep(2)
                    self.show('VERS.'+'{:>2}'.format(str(ota_updater.current_version)))
                    time.sleep(2)
                    self.display.clear()
                    self.display.show()
                    fota_master.machine_reset()
                    
            else:
                logging.debug(f"> Something went wrong, going into setup mode.")
                fota_master.setup_mode()
            
            server.run()

            
    def set_display_brightness(self):
        if self.show_function_name(self.button9):
            self.show('BRIGHT')
        else:
            brightness = self.display.brightness()
            self.show("{:>6}".format(brightness))
            if self.digit_pressed in [1,-1]:
                brightness+=self.digit_pressed
                if brightness >= 16 or brightness < 0:
                    brightness = 0
                self.display.brightness(brightness)
                access_data('display_brightness',brightness)
                self.digit_pressed = 0
                
    
    def set_sensors_nb(self):
        if self.show_function_name(self.button9):
            self.show('SENS.NB')
        else:
            sensors_nb = access_data('sensors_nb')
            sensors_list = ['V','V+T','V+T+P']
            self.show(str(sensors_list[sensors_nb-1]))
            if self.digit_pressed in [1,-1]:
                sensors_nb += self.digit_pressed
                self.digit_pressed = 0
                if sensors_nb < 1 or sensors_nb > 3:
                    sensors_nb = 1
                access_data('sensors_nb',sensors_nb)
            
                
    
    def set_auto_off(self):
        if self.show_function_name(self.button9):
            self.show('AUT.OFF')
        else:
            auto_off_delay = access_data('auto_off_delay')
            self.show(str(auto_off_delay)+'H')
            digit_mapping = {10:10,1:1, -1:-1,-10:-10}
            if self.digit_pressed in digit_mapping:
                auto_off_delay += self.digit_pressed
                self.digit_pressed = 0
                if auto_off_delay < 1 or auto_off_delay > 24:
                    auto_off_delay = 1
                access_data('auto_off_delay',auto_off_delay)
                            
    
    def set_backlight_brightness(self):
        if self.show_function_name(self.button9):
            self.show('BCKLGT')
        else:
            brightness = access_data('backlight_brightness') 
            self.show("{:>6}".format(brightness))
            digit_mapping = {10:10,1:1, -1:-1,-10:-10}
            if self.digit_pressed in digit_mapping:
                brightness+=self.digit_pressed
                self.set_backlight(0)
                if brightness >= 15 or brightness < 0:
                    brightness = 1
                access_data('backlight_brightness',brightness)
                self.digit_pressed = 0
                
                
    def set_gsensor_error(self):
        if self.show_function_name(self.button9):
            self.show('G.ERROR')
        else:
           
            g_error = access_data('g_error')
            self.show('X'+str(g_error[0])+'Y'+str(g_error[1]))
            x_digit_mapping = [10, -10]
            y_digit_mapping = [1, -1]
            if self.digit_pressed in x_digit_mapping:
                if -10 <= g_error[0] + self.digit_pressed / 10 < 10:
                     g_error[0] += int(self.digit_pressed / 100)
                access_data('g_error',g_error)
            elif self.digit_pressed in y_digit_mapping:
                if -10 < g_error[1] + self.digit_pressed < 10:
                    g_error[1] += int(self.digit_pressed/10)
                access_data('g_error',g_error)
            self.digit_pressed = 0
                
            
    def set_backlight(self,pin):
        display_brightness = access_data('display_brightness')
        backlight_brightness = access_data('backlight_brightness')
        duty = int(backlight_brightness * (2**12))
        if self.light_optocoupler.value():
            self.backlight_pwm.duty_u16(0)
            self.display.brightness(display_brightness)
        else:
            self.backlight_pwm.duty_u16(duty)
            self.display.brightness(display_brightness-5)
    
    
    def power_handler(self):
        self.powered = not self.powered
        if self.powered:
            logging.debug("System powered on")
            self.pwr_pin.high()
            self.init_i2c()
            self.led.high()
        else:
            logging.debug("System powered off")
            self.display.clear()
            self.display.show()
            time.sleep_ms(50)
            self.pwr_pin.low()
            self.led.low()
            
    def check_for_last_use(self):
        auto_off_delay = access_data('auto_off_delay')
        auto_off_delay = auto_off_delay * 60 * 60 * 1000
        access_data("current_time",self.rtc.datetime())
        if time.ticks_diff(time.ticks_ms(),self.last_use) > auto_off_delay:
            logging.debug(f"No activity for {auto_off_delay}ms")
            self.power_handler()
        
    def loop(self):
        while True:
            #self.watchdog.feed()
            if self.powered:
                self.displayed_function()
                if self.priority_counter == self.priority_interval[1] or  self.priority_counter == self.priority_interval[2]:
                    self.gps.get_GPS_data()
                if self.priority_counter == self.priority_interval[2]:
                    self.check_for_last_use()
                    if self.speed_limit_is_active:
                        self.check_for_overspeed()
                    if self.temperature_limit_is_active: 
                        self.check_for_overheat()
                    self.priority_counter = 0
                self.priority_counter += 1
        
            else:
                #lightsleep(4000)
                pass


OBC()
