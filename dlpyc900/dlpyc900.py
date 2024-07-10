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

Weirdly, byte 0 is not actually given in the replies from the device as far as I can tell, so remember that when parsing.
"""

import usb.core
import usb.util
import time
import numpy
import sys
from dlpyc900.erle import encode
from dlpyc900.errors import *
import array
import itertools

def flatten(nested_list : list[list]) -> list:
    """
    Flatten a list of lists. 
    See [this stackoverflow topic](https://stackoverflow.com/questions/952914/how-do-i-make-a-flat-list-out-of-a-list-of-lists).
    """
    return list(itertools.chain(*nested_list))

def bits_to_bytes(bits: str) -> list[int]:
    """Convert a string of bits to a list of bytes."""
    a = [int(bits[i:i+8], 2) for i in range(0, len(bits), 8)]
    a.reverse()
    return a

def number_to_bits(a: int, bitlen: int=8) -> str:
    """Convert a number to a binary string of specified bit length."""
    return format(a, '0{}b'.format(bitlen))

def bits_to_bools(a : str) -> tuple[int,...]:
    """Convert str of bits ('01101') to tuple of ints (0,1,1,0,1)"""
    return tuple(map(int,a))

def valid_n_bit(number : int, bits: int) -> bool:
    if type(number) != type(bits) != int:
        raise ValueError("Number and bits should be ints")
    if number < 0 or bits < 0:
        raise ValueError("Number and bits should be positive")
    return number < 2**bits

def parse_reply( reply : array.array ):
    """
    Split up the reply of the DMD into its constituant parts:
    (error_flag, flag_byte, error_flag, sequence_byte, length, data)
    Typically, you only care about the error, and the data.
    """
    if reply == None:
        return None
    flag_byte = number_to_bits(reply[0])
    sequence_byte = reply[1]
    length = reply[2] | (reply[3] << 8)  # Combine two bytes to form the length
    data = reply[4:4+length]
    error_flag = (reply[0] & 0x20) != 0
    return error_flag, flag_byte, sequence_byte, length, tuple(data)

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
        buffer.append(bits_to_bytes(flag_string)[0])

        # Sequence Byte
        buffer.append(sequence_byte)

        # Length Bytes (payload length + 2 command bytes)
        temp = bits_to_bytes(number_to_bits(len(data) + 2, 16))
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
        time.sleep(0.1) # give it some processing time...
        # read reply if required
        if mode == 'r':
            self.ans = self.dev.read(0x81, 64)
        else:
            self.ans = None
        self.check_for_error() # check if DMD is still working, while we are here anyway.
        return parse_reply(self.ans)

## status commands (section 2.1)
    def get_hardware_status(self) -> tuple[str, int]:
        """
        Generate report on hardware status

        Returns
        -------
        tuple[str, int]
            First element is report for printing. Second element indicates number of errors found.
        """
        ans = self.send_command('r',10,0x1A0A,[])
        ansbit = number_to_bits(ans[-1][0],8)
        statusmessage = ''
        errors = 0
        if ansbit[0] == "0":
            statusmessage += "Internal Initialization Error\n"
            errors += 1
        elif ansbit[0] == "1":
            statusmessage += "Internal Initialization Successful\n"
        if ansbit[1] == "0":
            statusmessage += "System is compatible\n"
        elif ansbit[1] == "1":
            statusmessage += "Incompatible Controller or DMD, or wrong firmware loaded on system\n"
            errors += 1
        if ansbit[2] == "0":
            statusmessage += "DMD Reset Controller has no errors\n"
        elif ansbit[2] == "1":
            statusmessage += "DMD Reset Controller Error: Multiple overlapping bias or reset operations are accessing the same DMD block\n"
            errors += 1
        if ansbit[3] == "0":
            statusmessage += "No Forced Swap Errors\n"
        elif ansbit[3] == "1":
            statusmessage += "Forced Swap Error occurred\n"
            errors += 1
        if ansbit[4] == "0":
            statusmessage += "No Secondary Controller Present\n"
        elif ansbit[4] == "1":
            statusmessage += "Secondary Controller Present and Ready\n"
        if ansbit[6] == "0":
            statusmessage += "Sequencer Abort Status reports no errors\n"
        elif ansbit[6] == "1":
            statusmessage += "Sequencer has detected an error condition that caused an abort\n"
            errors += 1
        if ansbit[7] == "0":
            statusmessage += "Sequencer reports no errors\n"
        elif ansbit[7] == "1":
            statusmessage += "Sequencer detected an error\n"
            errors += 1
        return statusmessage, errors
    
    def check_communication_status(self):
        """Check communication with DMD. Raise error when communication is not possible."""
        ans = self.send_command('r',10,0x1A49,[])
        ansbit = number_to_bits(ans[-1][0],8)
        if not (ansbit[0] == ansbit[2] == 0):
            raise DMDerror("Controller cannot communicate with DMD")
    
    def check_system_status(self):
        "Check system for internal memory errors. Raise error if I find one."
        ans = self.send_command('r',10,0x1A0B,[])
        ansbit = number_to_bits(ans[-1][0],8)
        if ansbit[0] == 0:
            raise DMDerror("Internal Memory Test failed")
    
    def get_main_status(self) -> tuple[int,int,int,int,int,int]:
        """
        Get main status of DMD.

        Returns
        -------
        tuple[int,int,int,int,int,int]
            Each index indicates something about the DMD:
            0: 0 - micromirrors are not parked, 1 - micromirrors are parked
            1: 0 - sequencer is stopped, 1 - sequencer is running
            2: 0 - video is running, 1 - video is frozen (displaying single frame)
            3: 0 - external source not locked, 1 - external source locked
            4: 0 - port 1 syncs not valid, 1 - port 1 syncs valid
            5: 0 - port 2 syncs not valid, 1 - port 2 syncs valid
        """
        ans = self.send_command('r',10,0x1A0C,[])
        ansbit = number_to_bits(ans[-1][0],8)
        return bits_to_bools(ansbit)[:6] 
 
    def get_hardware(self) -> tuple[str,str]:
        """
        Get hardware product code and firmware tag info

        Returns
        -------
        tuple[str,str]
            First element is hardware product code, second element is the 31 byte ASCII firmware tag information 
        """
        ans = self.send_command('r',10,0x0206,[])
        hw = ans[-1][0]
        fw = ans[-1][1:]
        hardware_pos = {0x00: "unknown",0x01: "DLP6500", 0x02:"DLP9000", 0x03:"DLP670S", 0x04: "DLP500YX", 0x05: "DLP5500"}
        try:
            hardware = hardware_pos[hw]
        except KeyError:
            hardware = "undocumented hardware"
        firmware =  ''.join(chr(i) for i in flatten(fw))
        return hardware, firmware

    def check_for_error(self):
        """
        check for errors in DMD operation, and raise them if there are any.
        """
        ans = self.send_command('r',0x22,0x0100,[])
        if ans[0] == 0:
            return None
        error_dict = {
            1  : "Batch file checksum error",
            2  : "Device failure",
            3  : "Invalid command number",
            4  : "Incompatible controller and DMD combination",
            5  : "Command not allowed in current mode",
            6  : "Invalid command parameter",
            7  : "Item referred by the parameter is not present",
            8  : "Out of resource (RAM or Flash)",
            9  : "Invalid BMP compression type",
            10 : "Pattern bit number out of range",
            11 : "Pattern BMP not present in flash",
            12 : "Pattern dark time is out of range",
            13 : "Signal delay parameter is out of range",
            14 : "Pattern exposure time is out of range",
            15 : "Pattern number is out of range",
            16 : "Invalid pattern definition (errors other than 9-15)",
            17 : "Pattern image memory address is out of range",
            255: "Internal Error",
        }
        try:
            error_message = error_dict[ans[0]]
        except KeyError:
            error_message = f"Undocumented error [{ans[0]}]"
        raise DMDerror(error_message)

## functions for parallel interface (to lock an external source) (section 2.3)
    def set_dual_pixel_mode(self):
        """Enable dual pixel mode. See page 35 of user manual."""
        self.send_command('w',2,0x1A03,[2,0,0,0])

    def set_display_to_parallel(self):
        """
        Switch display to the parallel interface (so not flash or test)
        See page 35 of user guide.
        """
        self.send_command('w',1,0x1A00,[0,3])

    def lock_displayport(self):
        """
        Lock external source over DisplayPort connection. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[2])
        self.set_display_to_parallel()
    
    def lock_hdmi(self):
        """
        Lock external source over HDMI connection. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[1])
        self.set_display_to_parallel()

    def lock_release(self):
        """
        Remove lock to external source. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[0])
        self.set_display_to_parallel()

    def check_source_lock(self) -> int:
        """Check if the source is locked, and if yes, via HDMI or DisplayPort. Returns 0 if not locked, 1 if HDMI, 2 if DisplayPort."""
        locked = self.get_main_status()[3]
        if locked:
            port = self.send_command('r',0,0x1A01,[])
            return port[0]
        else:
            return 0

## functions for display mode (section 2.4)
### functions for display mode selection (section 2.4.1)

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
        ans = self.send_command('r', 0x00, 0x1A1B, [])
        self.current_mode = self.display_modes_inv[ans[0]]
        return self.current_mode
    
## functions for setting Pattern Display LUT (section 2.4.4.3.5)

    def setup_pattern_LUT(self, exposuretime:int = 15000, darktime:int = 0, channel:int = 1, bitdepth:int = 8):
        """
        Settings for videopattern.
        
        Parameters
        ----------
        exposuretime : int, optional, in µs
            on-time of led in a 60hz period flash, by default 15000 µs
        darktime : int, optional, in µs
            off-time of led in a 60hz period flash, by default 0 µs
        channel : int, optional
            what channel to display, with 0: none, 1: red, 2: green, 3: red & green, 4: blue, 5: blue+red, 6: blue+green, 7: red+green+blue, by default "1"
        bitdepth : int, optional
            bitdepth of channel to concider, by default 8
        
        A few other parameters are there as well, but I don't need them/did not look into them, so they are simply set to 0.
        """
        pattern_index = 0
        pattern_index_bytes = [(pattern_index & 0xFF), ((pattern_index >> 8) & 0xFF)]
        exposuretime_bytes = [(exposuretime & 0xFF), ((exposuretime >> 8) & 0xFF), ((exposuretime >> 16) & 0xFF)]
        byte_5 = 0 | bitdepth-1 | channel | 0
        darktime_bytes = [(darktime & 0xFF), ((darktime >> 8) & 0xFF), ((darktime >> 16) & 0xFF)]
        byte_9 = 1 | 0 | 0 
        image_pattern_index = 0
        image_pattern_index_bytes = [(image_pattern_index & 0xFF), ((image_pattern_index >> 8) & 0xFF)]
        bit_position = 0
        bit_postion_byte = (bit_position & 0x1F) << 3
        byte_10_11 = [image_pattern_index_bytes[0], (image_pattern_index_bytes[1] | bit_postion_byte)]
        payload = list(pattern_index_bytes + exposuretime_bytes + [byte_5] + darktime_bytes + [byte_9] + byte_10_11)
        self.send_command('w',1,0x1A34,payload)

## Functions for Pattern Display (section 2.4.4.3)
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

## functions for power management (section 2.3.1.1 & 2.3.1.2)

    def standby(self):
        """Set DMD to standby"""
        self.stop_pattern()
        self.send_command('w',0x00,0x0200,[1])

    def wakeup(self):
        """Set DMD to wakeup"""
        self.send_command('w',0x00,0x0200,[0])

    def reset(self):
        """Reset DMD"""
        self.send_command('w',0x00,0x0200,[2])

    def idle_on(self):
        """Set DMD to idle mode"""
        self.stop_pattern()
        self.send_command('w',0x00,0x0201,[1])

    def idle_off(self):
        """Set DMD to active mode/deactivate idle mode"""
        self.send_command('w',0x00,0x0201,[3])

    def get_current_powermode(self) -> str:
        """
        Get the current power mode of the DMD. Options are normal, idle, or standby.

        Returns
        -------
        str
            current power mode.
        """
        idlestatus = self.send_command('r',0x00,0x0201,[])
        sleepstatus = self.send_command('r',0x00,0x0200,[])
        if sleepstatus == 0:
            if idlestatus == 0:
                return "normal"
            elif idlestatus == 1:
                return "idle"
        elif sleepstatus == 1:
            return "standby"
        else:
            return "undocumented state"

## pattern on the fly commands

    def definepattern(self,index,exposure,bitdepth,color,triggerin,darktime,triggerout,patind,bitpos):
        payload=[]
        index=number_to_bits(index,16)
        index=bits_to_bytes(index)
        for i in range(len(index)):
            payload.append(index[i])

        exposure=number_to_bits(exposure,24)
        exposure=bits_to_bytes(exposure)
        for i in range(len(exposure)):
            payload.append(exposure[i])
        optionsbyte=''
        optionsbyte+='1'
        bitdepth=number_to_bits(bitdepth-1,3)
        optionsbyte=bitdepth+optionsbyte
        optionsbyte=color+optionsbyte
        if triggerin:
            optionsbyte='1'+optionsbyte
        else:
            optionsbyte='0'+optionsbyte

        payload.append(bits_to_bytes(optionsbyte)[0])

        darktime=number_to_bits(darktime,24)
        darktime=bits_to_bytes(darktime)
        for i in range(len(darktime)):
            payload.append(darktime[i])

        triggerout=number_to_bits(triggerout,8)
        triggerout=bits_to_bytes(triggerout)
        payload.append(triggerout[0])

        patind=number_to_bits(patind,11)
        bitpos=number_to_bits(bitpos,5)
        lastbits=bitpos+patind
        lastbits=bits_to_bytes(lastbits)
        for i in range(len(lastbits)):
            payload.append(lastbits[i])



        self.send_command('w',0x00,0x1a34,payload)
        self.check_for_errors()

    def setbmp(self,index,size):
        payload=[]

        index=number_to_bits(index,5)
        index='0'*11+index
        index=bits_to_bytes(index)
        for i in range(len(index)):
            payload.append(index[i]) 


        total=number_to_bits(size,32)
        total=bits_to_bytes(total)
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
                leng=number_to_bits(504,16)
                bits=504
            else:
                leng=number_to_bits(size%504,16)
                bits=size%504
            leng=bits_to_bytes(leng)
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