import RPi.GPIO as GPIO
import time

# Set the GPIO mode
GPIO.setmode(GPIO.BCM)

# Define the GPIO pins connected to the PWM signal of the servos
servo_pin_1 = 33
servo_pin_2 = 32

# Set the PWM frequency (in Hz)
pwm_frequency = 50  # Standard PWM frequency for servos

# Set the duty cycle range (in %) for each servo
duty_cycle_min = 2.5  # Minimum duty cycle for the servo (0 degrees)
duty_cycle_max = 12.5  # Maximum duty cycle for the servo (180 degrees)

# Initialize the PWM pins
GPIO.setup(servo_pin_1, GPIO.OUT)
pwm_1 = GPIO.PWM(servo_pin_1, pwm_frequency)
GPIO.setup(servo_pin_2, GPIO.OUT)
pwm_2 = GPIO.PWM(servo_pin_2, pwm_frequency)

# Start PWM with a duty cycle of 0 for each servo
pwm_1.start(0)
pwm_2.start(0)

def set_angle(servo, angle):
    # Convert angle to duty cycle
    duty_cycle = ((angle / 180.0) * (duty_cycle_max - duty_cycle_min)) + duty_cycle_min
    # Change duty cycle to move the servo
    servo.ChangeDutyCycle(duty_cycle)
    # Wait for the servo to reach the desired position
    time.sleep(0.5)

if __name__ == "__main__":
    try:
        # Move both servos to 0 degrees (minimum position)
        set_angle(pwm_1, 0)
        set_angle(pwm_2, 0)
        # Wait for 1 second
        time.sleep(1)
        
        # Move both servos to 90 degrees (middle position)
        set_angle(pwm_1, 90)
        set_angle(pwm_2, 90)
        # Wait for 1 second
        time.sleep(1)
        
        # Move both servos to 180 degrees (maximum position)
        set_angle(pwm_1, 180)
        set_angle(pwm_2, 180)
        # Wait for 1 second
        time.sleep(1)
    
    except KeyboardInterrupt:
        print("Exiting program")
    
    finally:
        # Stop PWM and cleanup GPIO
        pwm_1.stop()
        pwm_2.stop()
        GPIO.cleanup()