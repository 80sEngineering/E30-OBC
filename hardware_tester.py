import ht16k33_driver
import time
from button import Button
from machine import Pin, I2C
from imu import MPU6050

i2c = I2C(id=1, sda=Pin(2), scl=Pin(3), freq = 9600)
display = ht16k33_driver.Seg14x4(i2c)
display.fill()
mpu = MPU6050(i2c)

def button_manager(button_id, long_press):
    display.put_text(str(button_id))
    display.show()
    time.sleep_ms(500)
    
button1 = Button(6, 1, button_manager)
button2 = Button(7, 2, button_manager)
button3 = Button(8, 3, button_manager)
button4 = Button(9, 4, button_manager)
button5 = Button(10, 5, button_manager)
button6 = Button(11, 6, button_manager)
button7 = Button(12, 7, button_manager)
button8 = Button(13, 8, button_manager)
button9 = Button(14, 9, button_manager)
button10 = Button(18, 10, button_manager)
button11 = Button(19, 11, button_manager)
button12 = Button(20, 12, button_manager)
button13 = Button(21, 13, button_manager)
led = Pin(15,Pin.OUT)
led.toggle()

while True:
    display.put_text(str(round(mpu.accel.x,1)))
    display.show()
    