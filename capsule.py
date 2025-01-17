MAX_BUFFER_SIZE = 1024
ADDITIONAL_BYTES = 5

PRA_DEFAULT = 0xFF
PRB_DEFAULT = 0xFA

class ParserState:
    PREAMBLE_A = 0
    PREAMBLE_B = 1
    PACKET_ID = 2
    LENGTH = 3
    PAYLOAD = 4
    CRC = 5

class Capsule:
    def __init__(self, function, PRAIn=PRA_DEFAULT, PRBIn=PRB_DEFAULT):
        self.PRA = PRAIn
        self.PRB = PRBIn
        self.currentState = ParserState.PREAMBLE_A
        self.lenCount = 0
        self.functionCallBack = function
        self.classPtr = None

    def set_callback_class(self, function, tptrIn):
        self.functionCallBackClass = function
        self.classPtr = tptrIn

    def get_coded_len(self, lenIn):
        return lenIn + ADDITIONAL_BYTES

    def decode(self, dataIn):
        if self.currentState == ParserState.PREAMBLE_A:
            if dataIn == self.PRA:
                self.currentState = ParserState.PREAMBLE_B
        elif self.currentState == ParserState.PREAMBLE_B:
            if dataIn == self.PRB:
                self.currentState = ParserState.PACKET_ID
                self.packetId = 0x00
                self.buffer = [0] * MAX_BUFFER_SIZE
            else:
                self.currentState = ParserState.PREAMBLE_A
        elif self.currentState == ParserState.PACKET_ID:
            self.packetId = dataIn
            self.currentState = ParserState.LENGTH
        elif self.currentState == ParserState.LENGTH:
            self.len = dataIn
            self.lenCount = 0
            self.currentState = ParserState.PAYLOAD
        elif self.currentState == ParserState.PAYLOAD:
            if self.lenCount < self.len:
                self.buffer[self.lenCount] = dataIn
                self.lenCount += 1
                if self.lenCount == self.len:
                    self.currentState = ParserState.CRC
            else:
                self.currentState = ParserState.CRC
        elif self.currentState == ParserState.CRC:
            check_sum = 0
            for i in range(self.len):
                check_sum += self.buffer[i]
            if check_sum % 256 == dataIn:  # Ensure check_sum stays within [0, 255]
                if self.classPtr:
                    self.classPtr.functionCallBackClass(self.packetId, self.buffer, self.len)
                else:
                    self.functionCallBack(self.packetId, self.buffer, self.len)
            else:
                # Should return error code maybe?
                pass
            self.currentState = ParserState.PREAMBLE_A

    def encode(self, packetId, packetIn, lenIn):
        lenOut = self.get_coded_len(lenIn)
        packetOut = [0] * lenOut

        packetOut[0] = self.PRA
        packetOut[1] = self.PRB
        packetOut[2] = packetId
        packetOut[3] = lenIn

        check_sum = 0
        for i in range(lenIn):
            packetOut[i + 4] = packetIn[i]
            check_sum = (check_sum + packetIn[i]) % 256

        packetOut[lenIn + 4] = check_sum
        return packetOut
