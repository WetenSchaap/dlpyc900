"""
Content of this file is based on Pycrafter 6500 repo, as well as the [dlpc900 user guide](http://www.ti.com/lit/pdf/dlpu018). Some docstrings contain references to pages in this guide.

In general, all commands and replies have the same structure:

byte 0: report ID, set to 0
## Header bytes
byte 1: flag byte
    bit 7: read/write
    bit 6: reply
    bit 5: error
    bit 4:3: reserved
    bit 2:1: destination
byte 2: sequence byte - replies to a message will match sequence bytes of it
byte 3: Length LSB - number of bytes in payload
byte 4: Length MSB - number of bytes in payload
## Payload bytes
byte 5 onward: At least the USB command, followed by any data.

Weirdly, byte 0 is not actually given in the replies from the device, as far as I can tell, so remember theat when parsing.
"""

import usb.core
import usb.util
import time
import numpy
import sys
from dlpyc900.erle import encode
import array

def bitstobytes(bits: str) -> list[int]:
    """Convert a string of bits to a list of bytes."""
    a = [int(bits[i:i+8], 2) for i in range(0, len(bits), 8)]
    a.reverse()
    return a

def convlen(a: int, bitlen: int) -> str:
    """Convert a number to a binary string of specified bit length."""
    return format(a, '0{}b'.format(bitlen))

def valid_n_bit(number : int, bits: int) -> bool:
    if type(number) != type(bits) != int:
        raise ValueError("Number and bits should be ints")
    if number < 0 or bits < 0:
        raise ValueError("Number and bits should be positive")
    return number < 2**bits

def parse_reply( reply : array.array ):
    """
    Split up the reply of the DMD into its constituant parts:
    (report_id, flag_byte, error_flag, sequence_byte, length, data)
    Typically, you only care about the error, and the data.
    """
    flag_byte = number_to_bits(reply[0])
    sequence_byte = reply[1]
    length = reply[2] | (reply[3] << 8)  # Combine two bytes to form the length
    data = reply[4:4+length]
    error_flag = (reply[0] & 0x20) != 0
    return error_flag, flag_byte, sequence_byte, length, tuple(data)

def number_to_bits( nr:int ) -> str:
    return format(nr, '08b')

class dmd():
    """
    DMD controller class
    """
    def __init__(self):
        self.dev=usb.core.find(idVendor=0x0451 ,idProduct=0xc900 )

        self.dev.set_configuration()

        self.ans=[]
        self.current_mode = "pattern"
        self.display_modes = {'video':0, 'pattern':1, 'video-pattern':2, 'otf':3}
        self.display_modes_inv = {0:'video', 1:'pattern', 2:'video-pattern', 3:'otf'}
        
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        # Exception handling could be included here
        self.standby()

## direct communication

    def send_command(self, mode: str, sequence_byte: int, command: int, data: list[int] = None):
        """
        Send a command to the DMD device.

        :param mode: 'r' for read, 'w' for write
        :param sequence_byte: A byte to identify the command sequence, so you know what reply belongs to what command. Choose arbitrary number, like 0x00. do not re-use.
        :param command: The command to be sent (16-bit integer), so for instance '0x0200'
        :param data: List of data bytes associated with the command. Often just one to set a mode, e.g. [1] for option 1.
        
        In all these cases you can give the hexidecimal number (like 0x1A1B) or the normal one (6683), Python does not care.
        """
        if data is None:
            data = []

        buffer = []

        # Flag Byte
        flag_string = '1' if mode == 'r' else '0'
        flag_string += '1000000'
        buffer.append(bitstobytes(flag_string)[0])

        # Sequence Byte
        buffer.append(sequence_byte)

        # Length Bytes (payload length + 2 command bytes)
        temp = bitstobytes(convlen(len(data) + 2, 16))
        buffer.append(temp[0])
        buffer.append(temp[1])

        # Command Bytes (little-endian order)
        buffer.append(command & 0xFF)         # Lower byte
        buffer.append((command >> 8) & 0xFF)  # Upper byte

        # Add data to buffer
        if len(buffer) + len(data) < 65:
            buffer.extend(data)
            buffer.extend([0x00] * (64 - len(buffer)))
            self.dev.write(1, buffer)
        else:
            remaining_data = data
            buffer.extend(remaining_data[:58])
            self.dev.write(1, buffer)
            remaining_data = remaining_data[58:]

            while len(remaining_data) > 0:
                chunk = remaining_data[:64]
                remaining_data = remaining_data[64:]
                if len(chunk) < 64:
                    chunk.extend([0x00] * (64 - len(chunk)))
                self.dev.write(1, chunk)
        # read reply to self.ans
        if mode == 'r':
            time.sleep(0.4)
            self.ans = self.dev.read(0x81, 64)

    def check_for_errors(self):
        """
        check for error reports in the dlp answer
        """
        self.send_command('r',0x22,0x0100,[])
        if self.ans[6] != 0:
            print( self.ans[6] )

    def read_reply(self):
        """Print the dlp answer"""
        for i in self.ans:
            print( hex(i) )

## status commands
    def get_main_status(self):
        self.send_command('r',10,0x1A0C,[])

## function to lock source correctly (hopefully)
### See page 40 of userguide. maybe page 34 is also related, but not sure.
    def lock_displayport(self):
        # page 35? or page 40?
        # run command
        self.send_command('w',0,0x1A01,[2])
        self.send_command('w',1,0x1A00,[0,3])
        
    def set_dual_pixel_mode(self):
        # page 35
        # option 2: Data Port 1-2, Dual Pixel mode. Even pixel on port 1, Odd pixel on port 2
        self.send_command('w',2,0x1A03,[2,0,0,0])
    
## functions for display mode selection

    def set_display_mode(self, mode: str):
        """
        Set the display mode

        See page 56 of user guide.
        
        Parameters
        ----------
        mode : str
            mode name: can be 'video', 'pattern', 'video-pattern', 'otf'(=on the fly).
        """
        if mode not in self.display_modes.keys():
            raise ValueError(f"mode '{mode}' unknown")
        elif mode == 'video-pattern' and self.current_mode != 'video':
            raise ValueError(f"To change to Video Pattern Mode the system must first change to Video Mode with the desired source enabled and sync must be locked before switching to Video Pattern Mode.")
        self.send_command('w',0x00,0x1A1B,[self.display_modes[mode]])
        time.sleep(0.5) # required for video-projection mode, just as a safety.
        if self.get_display_mode() != mode:
            raise ConnectionError("Mode activation failed.")
        
    def get_display_mode(self) -> str:
        """
        Get the current display mode.

        Returns
        -------
        mode : str
            mode name: can be 'video', 'pattern', 'video-pattern', 'otf'(=on the fly).
        """
        command = 0x1A1B
        self.send_command('r', 0x00, command, [])
        mode = self.ans[6] & 0x03  # Extract bits 1:0 from the response byte.
        self.current_mode = self.display_modes_inv[mode]
        return self.current_mode
    
## functions for setting video-pattern mode
# see page 73 in user guide

    def setup_videopattern(self, exposuretime:int = 15000, channel:int = 1, bitdepth:int = 8):
        """
        Settings for videopattern.
        WARNING - this will NOT work with the regular send_command parameter

        Parameters
        ----------
        exposuretime : int, optional
            on-time of led in a 60hz period flash, by default 15000 µs
        channel : int, optional
            what channel to display, with 0: none, 1: red, 2: green, 3: red & green, 4: blue, 5: blue+red, 6: blue+green, 7: red+green+blue, by default "1"
        bitdepth : int, optional
            bitdepth of channel to concider, by default 8
        """
        raise NotImplementedError("not functional yet!")
        if self.current_mode != 'video-pattern':
            raise ValueError("command can only be run in video-pattern mode.")
        # construct command p 73. 
        self.send_command('w',1,0x1A34,[0,exposuretime,[0,bitdepth-1,channel,0],0,[1,0]])
        return 0

## Functions to control pattern display
    def start_pattern(self):
        """
        Start pattern display sequence (any mode)
        """
        self.send_command('w',5,0x1A24,[2])

    def pause_pattern(self):
        """
        Pause pattern display sequence (any mode)
        """
        self.send_command('w',5,0x1A24,[1])
        
    def stop_pattern(self):
        """
        Stop pattern display sequence (any mode)
        """
        self.send_command('w',5,0x1A24,[0])

## functions for idle mode activation

    def idle_on(self):
        """Set DMD to idle mode"""
        self.stop_pattern()
        self.send_command('w',0x00,0x0201,[1])
        self.check_for_errors()

    def idle_off(self):
        """Set DMD to active mode/deactivate idle mode"""
        self.send_command('w',0x00,0x0201,[3])
        self.check_for_errors()

## functions for power management

    def standby(self):
        """Set DMD to standby"""
        self.stop_pattern()
        self.send_command('w',0x00,0x0200,[1])
        self.check_for_errors()

    def wakeup(self):
        """Set DMD to wakeup"""
        self.send_command('w',0x00,0x0200,[0])
        self.check_for_errors()

    def reset(self):
        """Reset DMD"""
        self.send_command('w',0x00,0x0200,[2])
        self.check_for_errors()

## test write and read operations, as reported in the dlpc900 programmer's guide

    def test_read(self):
        """
        Perform read-test
        """
        self.send_command('r',0xff,0x1100,[])
        self.read_reply()

    def test_write(self):
        """
        Perform write-test
        """
        self.send_command('w',0x22,0x1100,[0xff,0x01,0xff,0x01,0xff,0x01])
        self.check_for_errors()

## unused things

    def definepattern(self,index,exposure,bitdepth,color,triggerin,darktime,triggerout,patind,bitpos):
        payload=[]
        index=convlen(index,16)
        index=bitstobytes(index)
        for i in range(len(index)):
            payload.append(index[i])

        exposure=convlen(exposure,24)
        exposure=bitstobytes(exposure)
        for i in range(len(exposure)):
            payload.append(exposure[i])
        optionsbyte=''
        optionsbyte+='1'
        bitdepth=convlen(bitdepth-1,3)
        optionsbyte=bitdepth+optionsbyte
        optionsbyte=color+optionsbyte
        if triggerin:
            optionsbyte='1'+optionsbyte
        else:
            optionsbyte='0'+optionsbyte

        payload.append(bitstobytes(optionsbyte)[0])

        darktime=convlen(darktime,24)
        darktime=bitstobytes(darktime)
        for i in range(len(darktime)):
            payload.append(darktime[i])

        triggerout=convlen(triggerout,8)
        triggerout=bitstobytes(triggerout)
        payload.append(triggerout[0])

        patind=convlen(patind,11)
        bitpos=convlen(bitpos,5)
        lastbits=bitpos+patind
        lastbits=bitstobytes(lastbits)
        for i in range(len(lastbits)):
            payload.append(lastbits[i])



        self.send_command('w',0x00,0x1a34,payload)
        self.check_for_errors()

    def setbmp(self,index,size):
        payload=[]

        index=convlen(index,5)
        index='0'*11+index
        index=bitstobytes(index)
        for i in range(len(index)):
            payload.append(index[i]) 


        total=convlen(size,32)
        total=bitstobytes(total)
        for i in range(len(total)):
            payload.append(total[i])         
        
        self.send_command('w',0x00,0x1a2a,payload)
        self.check_for_errors()

    def bmpload(self,image,size):
        """
        bmp loading function, divided in 56 bytes packages
        max  hid package size=64, flag bytes=4, usb command bytes=2
        size of package description bytes=2. 64-4-2-2=56
        """

        packnum=size//504+1

        counter=0

        for i in range(packnum):
            if i %100==0:
                print (i,packnum)
            payload=[]
            if i<packnum-1:
                leng=convlen(504,16)
                bits=504
            else:
                leng=convlen(size%504,16)
                bits=size%504
            leng=bitstobytes(leng)
            for j in range(2):
                payload.append(leng[j])
            for j in range(bits):
                payload.append(image[counter])
                counter+=1
            self.send_command('w',0x11,0x1a2b,payload)


            self.check_for_errors()

    def defsequence(self,images,exp,ti,dt,to,rep):

        self.stopsequence()

        arr=[]

        for i in images:
            arr.append(i)

        num=len(arr)

        encodedimages=[]
        sizes=[]

        for i in range((num-1)//24+1):
            print ('merging...')
            if i<((num-1)//24):
                imagedata=arr[i*24:(i+1)*24]
            else:
                imagedata=arr[i*24:]
            print ('encoding...')
            imagedata,size=encode(imagedata)

            encodedimages.append(imagedata)
            sizes.append(size)

            if i<((num-1)//24):
                for j in range(i*24,(i+1)*24):
                    self.definepattern(j,exp[j],1,'111',ti[j],dt[j],to[j],i,j-i*24)
            else:
                for j in range(i*24,num):
                    self.definepattern(j,exp[j],1,'111',ti[j],dt[j],to[j],i,j-i*24)

        self.configurelut(num,rep)

        for i in range((num-1)//24+1):
        
            self.setbmp((num-1)//24-i,sizes[(num-1)//24-i])

            print ('uploading...')
            self.bmpload(encodedimages[(num-1)//24-i],sizes[(num-1)//24-i])