#include "AccelStepper.h"

#define X_STEP_PIN 12
#define X_DIR_PIN 13
#define ENABLE_PIN 9
#define HOME_SWITCH_X 7
#define BUTTON_CW_PIN 2  
#define BUTTON_CCW_PIN 3 

AccelStepper stepperX(1, X_STEP_PIN, X_DIR_PIN);
const int stepIncrement = 3;  // Define el tamaño del paso para movimientos incrementales
const long int limite_safe = 5600;  // Límite seguro para el movimiento del motor

void setup() {
  Serial.begin(9600);
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(ENABLE_PIN, LOW);  // Inicialmente desactivado
  pinMode(HOME_SWITCH_X, INPUT_PULLUP);
  pinMode(BUTTON_CW_PIN, INPUT_PULLUP);
  pinMode(BUTTON_CCW_PIN, INPUT_PULLUP);
  stepperX.setMaxSpeed(300);
  stepperX.setAcceleration(100);
  homing();
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    activateMotor();
    handleSerialCommand(command);
  }
}

void homing() {
  activateMotor();
  while (digitalRead(HOME_SWITCH_X) == LOW) {
    stepperX.moveTo(stepperX.currentPosition() - 1);
    stepperX.run();
    delay(1);
  }
  stepperX.setCurrentPosition(0);
  Serial.println("Homing completado");
  deactivateMotor();
}

void handleSerialCommand(String command) {
  if (command.startsWith("GOTO ")) {
    long position = command.substring(5).toInt();
    if (position >= 0 && position <= limite_safe) {
      stepperX.moveTo(position);
      while (stepperX.distanceToGo() != 0) {
        stepperX.run();
      }
      Serial.println("Movimiento completado a posición: " + String(position));
      deactivateMotor();
    } else {
      Serial.println("Error: Posición fuera de límites");
    }
  } else if (command == "MOVE +") {
    long newPosition = stepperX.currentPosition() + stepIncrement;
    if (newPosition <= limite_safe) {
      stepperX.move(stepIncrement);
      stepperX.runToPosition();
      Serial.println("Movido + a: " + String(newPosition));
    } else {
      Serial.println("Error: Movimiento fuera de límites");
    }
    deactivateMotor();
  } else if (command == "MOVE -") {
    long newPosition = stepperX.currentPosition() - stepIncrement;
    if (newPosition >= 0) {
      stepperX.move(-stepIncrement);
      stepperX.runToPosition();
      Serial.println("Movido - a: " + String(newPosition));
    } else {
      Serial.println("Error: Movimiento fuera de límites");
    }
    deactivateMotor();
  } else if (command == "HOME") {
    homing();
  }
}

void activateMotor() {
  digitalWrite(ENABLE_PIN, HIGH); // HIGH para activar
}

void deactivateMotor() {
  digitalWrite(ENABLE_PIN, LOW); // LOW para desactivar
  Serial.println("Motor desactivado por inactividad");
}
