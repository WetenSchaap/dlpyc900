"""
Content of this file is based on Pycrafter 6500 repo, as well as the [dlpc900 user guide](http://www.ti.com/lit/pdf/dlpu018). Some docstrings contain references to pages in this guide.

Please see the example folder in this repo, which explains a bit more how this works (because I keep forgetting).
"""
import usb.core
import time
import math
from dlpyc900.erle import enhanced_rle_encode
from dlpyc900.dlp_errors import *
import PIL.Image as Image
import warnings

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

def parse_reply( reply : tuple[bool,int,int,int,tuple[int,...]] ):
    """
    Split up the reply of the DMD into its constituant parts:
    (error_flag, flag_byte, sequence_byte, length, data)
    Typically, you only care about the error, sequence_byte and the data.
    """
    if reply == None:
        return None
    flag_byte = number_to_bits(reply[0])
    sequence_byte = reply[1]
    length = reply[2] | (reply[3] << 8)  # Combine two bytes to form the length
    data = reply[4:4+length]
    error_flag = (reply[0] & 0x20) != 0
    return error_flag, flag_byte, sequence_byte, length, tuple(data)

def list_to_int(byte_list:list[int]|tuple[int]) -> int:
    """
    Convert a list of integers (0-255) to a big-endian integer.

    Parameters
    ----------
    byte_list : list[int]
        Each element is treated as an unsigned byte.

    Returns
    -------
    int
        The integer value of the concatenated bytes.
    """
    # note that in the things below, the order is always inverted basically, so do that as well here:
    byte_list_r = list(byte_list)
    byte_list_r.reverse()
    if not all(0 <= b <= 255 for b in byte_list_r):
        raise ValueError("All elements must be in the range 0-255")
    return int.from_bytes(byte_list_r, byteorder='big', signed=False)

def bytes_to_text(byte_list:list[int]|tuple[int]) -> str:
    message = ''
    for c in byte_list:
        if c == 0:
            break
        message += chr(c)
    return message

class dmd():
    """
    DMD controller class
    """
    def __init__(self):
        self.dev = usb.core.find(idVendor=0x0451 ,idProduct=0xc900 )
        if self.dev == None:
            raise DMDerror("Connection to DMD could not be established")
        self.dev.set_configuration()
        self.current_mode = "pattern"
        self.display_modes = {'video':0, 'pattern':1, 'video-pattern':2, 'otf':3}
        self.display_modes_inv = {0:'video', 1:'pattern', 2:'video-pattern', 3:'otf'}
        # lets check if connection actually works:
        try:
            self.hardware = self.get_hardware()[0]
        except DMDerror:
            raise DMDerror("Connection to dmd was not succesfull")
        
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        # Exception handling could be included here
        self.standby()

## direct communication

    def send_command(self, mode: str, sequence_byte: int, command: int, payload: list[int]|None = None):
        """
        Send a command to the DMD device.
        
        Parameters
        ----------
        mode : char
            'r' for read, 'w' for write
        sequence_byte : int
            A byte to identify the command sequence, so you know what reply belongs to what command. Choose arbitrary number that fits in 1 byte.
        command : int
            The command to be sent (16-bit integer), as found in the user guide. For instance '0x0200'
        payload : int, optional
            List of data bytes associated with the command. Leave empty when reading. Often just a simple number to set a mode, e.g. [1] for option 1. If more complex, you need to craft the byte(s) yourself.
        """
        if payload is None:
            payload = []

        buffer = []

        # Flag Byte
        flag_string = '1' if mode == 'r' else '0'
        flag_string += '1000000'
        buffer.append(bits_to_bytes(flag_string)[0])

        # Sequence Byte
        buffer.append(sequence_byte)

        # Length Bytes (payload length + 2 command bytes)
        temp = bits_to_bytes(number_to_bits(len(payload) + 2, 16))
        buffer.append(temp[0])
        buffer.append(temp[1])

        # Command Bytes (little-endian order)
        buffer.append(command & 0xFF)         # Lower byte
        buffer.append((command >> 8) & 0xFF)  # Upper byte

        # Add data to buffer
        if len(buffer) + len(payload) < 65:
            buffer.extend(payload)
            buffer.extend([0x00] * (64 - len(buffer)))
            try:
                self.dev.write(1, buffer)
            except usb.USBError:
                # sometimes timouts occur. If that happens, just wait a very short time and rerun, that will fix the issue in a good 90% of the cases.
                time.sleep(0.1)
                self.dev.write(1, buffer)
        else:
            remaining_data = payload
            buffer.extend(remaining_data[:58])
            self.dev.write(1, buffer)
            remaining_data = remaining_data[58:]

            while len(remaining_data) > 0:
                chunk = remaining_data[:64]
                remaining_data = remaining_data[64:]
                if len(chunk) < 64:
                    chunk.extend([0x00] * (64 - len(chunk)))
                try:
                    self.dev.write(1, chunk)
                except usb.USBError:
                    # sometimes timouts occur. If that happens, just wait a very short time and rerun, that will fix the issue in a good 90% of the cases.
                    time.sleep(0.1)
                    self.dev.write(1, chunk)
        # read reply if required
        if mode == 'r':
            time.sleep(0.1) # give it some processing time...
            answer = self.dev.read(0x81, 64)
            answer_parsed = parse_reply(answer)
            if not answer_parsed[0]:
                warnings.warn('DMD reply has error flag set!')
        else:
            answer_parsed = None
        return answer_parsed

## status commands (section 2.1)
    def get_hardware_status(self) -> tuple[int,int,int,int,int,int,int,int]:
        """
        Get hardware status. Check user guide section 2.1.1 for details on what the statuses indicate, or run get_hardware_status_for_humans for a human-readable report.

        Returns
        -------
        tuple[int,int,int,int,int,int,int,int]
        """
        ans = self.send_command('r',10,0x1A0A)
        return bits_to_bools( number_to_bits(ans[-1][0],8) )
    
    def get_hardware_status_for_humans(self) -> str:
        """
        Generate human-readable report on hardware status. Uses get_hardware_status result and parses it. Reports are directly taken from Table 2-2 of the manual.

        Returns
        -------
        str
        """
        ansbit = self.get_hardware_status()
        statusmessage = ''
        if not ansbit[0]:
            statusmessage += "Internal Initialization Error\n"
        else:
            statusmessage += "Internal Initialization Successful\n"
        if not ansbit[1]:
            statusmessage += "System is compatible\n"
        else:
            statusmessage += "Incompatible Controller or DMD, or wrong firmware loaded on system\n"
        if not ansbit[2]:
            statusmessage += "DMD Reset Controller has no errors\n"
        else:
            statusmessage += "DMD Reset Controller Error: Multiple overlapping bias or reset operations are accessing the same DMD block\n"
        if not ansbit[3]:
            statusmessage += "No Forced Swap Errors\n"
        else:
            statusmessage += "Forced Swap Error occurred\n"
        if ansbit[4]:
            statusmessage += "No Secondary Controller Present\n"
        else:
            statusmessage += "Secondary Controller Present and Ready\n"
        if not ansbit[6]:
            statusmessage += "Sequencer Abort Status reports no errors\n"
        else:
            statusmessage += "Sequencer has detected an error condition that caused an abort\n"
        if not ansbit[7]:
            statusmessage += "Sequencer reports no errors\n"
        else:
            statusmessage += "Sequencer detected an error\n"
        return statusmessage

    def check_communication_status(self):
        """Check communication with DMD. Raise error when communication is not possible."""
        ans = self.send_command('r',10,0x1A49,[])
        try:
            ansbit = number_to_bits(ans[-1][0],8)
            if not (ansbit[0] == ansbit[2] == 0):
                raise DMDerror("Controller cannot communicate with DMD")
        except IndexError: # not sure why this happens, but it cannot be good.
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
        ans = self.send_command('r',10,0x0206)
        hw = ans[-1][0]
        fw = ans[-1][1:]
        hardware_pos = {0x00:"unknown",0x01: "DLP6500", 0x02:"DLP9000", 0x03:"DLP670S", 0x04: "DLP500YX", 0x05: "DLP5500"}
        try:
            hardware = hardware_pos[hw]
        except KeyError:
            hardware = "undocumented hardware"
        firmware =  bytes_to_text( fw )
        return hardware, firmware

    def check_for_error(self, verbose=True) -> tuple[int,str]:
        """
        Check for errors in last executed DMD command. Replies with the error code and description, check manual section 2.1.6. Error code 0 indicates no error.
        When verbose is True (=default), the error message is also printed.
        """
        ans = self.send_command('r', 0x22, 0x0100)
        if len(ans[-1]) == 0:
            # This happens sometimes, idk why?
            # Just pretend all is okay
            return (0, "No Error")
        errorcode = ans[-1][0]
        error_dict = {
            0  : "No Error",
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
            error_message = error_dict[errorcode]
        except KeyError:
            error_message = f"Undocumented error [{errorcode}]"
        if verbose:
            print(error_message)
        return errorcode, error_message

    def read_error_description(self, verbose=True) -> str:
        """
        Read error description, if there is one.
        """
        ans = self.send_command('r', 0, 0x0101)
        descr = ans[-1]
        message = bytes_to_text( descr )
        if verbose:
            print( message )
        return message

## Control commands (Section 2.2). 
# Commands in this section are only valid after you ernter program mode using enter_program_mode! When in program mode, commands outside this section do not work!

    def get_status_flash(self) -> dict:
        """
        This command indicates if the flash is ready to be programmed and also if a flash operation is in progress. It returns a heap of data in a dict. See manual section 2.2.1 for details about meaning.
        You can only run this if you are in programming mode!
        """
        result = dict()
        ans = self.send_command('r',28,0x0000)
        if ans[-2] < 5:
            raise DMDerror("Did not receive flash data. Are you sure you are in program mode?")
        reply = ans[-1]
        # byte 0:
        byte0 = bits_to_bools( number_to_bits(reply[0]) )
        result["primary_ready"] = byte0[0]
        result["primary_busy"] = byte0[3]
        result["primary_progmode"] = byte0[7]
        result["secondary_present"] = byte0[5]
        result["secondary_ready"] = byte0[1]
        result["secondary_busy"] = byte0[2]
        result["secondary_progmode"] = byte0[6]
        # byte 1
        byte1 = number_to_bits(reply[1])
        result["majorversion"] = list_to_int(bits_to_bytes(byte1[:4]))
        result["minorversion"] = list_to_int(bits_to_bytes(byte1[4:]))
        # byte 2
        result["patchversion"] = reply[2]
        # byte 3
        result["controller_id"] = reply[3]
        # byte 4
        result["bootloader_id"] = {101:'single DLPC900',144:'dual DLPC900'}[reply[4]]
        # other bytes we ignore
        return result

    def enter_program_mode(self):
        """
        This command tells the controller to enter its programming mode and jump to the boot loader. If the boot loader receives this command, then the command has no effect.
        """
        self.send_command('r',42,0x3001,[1])

    def exit_program_mode(self):
        """
        This command tells the controller to exit its programming mode. If the application receives the exit command, the command has no effect.
        """
        self.send_command('r',41,0x0030,[2])

## Chipset Control Commands (section 2.3)
### functions for power management (section 2.3.1.1 & 2.3.1.2)

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
        idlestatus = self.send_command('r',0x00,0x0201,[])[-1][0]
        sleepstatus = self.send_command('r',0x00,0x0200,[])[-1][0]
        if sleepstatus == 0:
            if idlestatus == 0:
                return "normal"
            elif idlestatus == 1:
                return "idle"
        elif sleepstatus == 1:
            return "standby"
        else:
            return "undocumented state"

### Parallel Interface Configuration (e.g. lock source to displayport connecter),(section 2.3.2/2.3.3)
    def set_port_clock_definition(self, data_port:int, px_clock:int, data_enable:int, vhsync:int):
        """
        This command selects which port(s) the RGB data is on and which pixel clock, data enable, and syncs to use.

        See also get_port_clock_definition
        
        Parameters
        ----------
        data_port : int
            0: use data port 1, 1: use data port 2, 2: use port 1-2 dual px, 3: use port 2-1 dual px.
        px_clock : int
            0: pixel clock 1, 1: use pixel clock 2, 3: use pixel clock 3
        data_enable : int
            0: data enable 1, 1: data enable 2
        vhsync : int
            0: P1 VSync & P1 HSync, 1: P2 VSync & P2 HSync
        """
        payload = 0
        payload |= data_port & 0x03
        payload |= (px_clock & 0x03) << 2
        payload |= (data_enable & 0x01) << 4
        payload |= (vhsync & 0x01) << 5
        self.send_command('w', 2, 0x1A03, [payload])

    def get_port_clock_definition(self) -> tuple[int,int,int,int]:
        """
        Read which port(s) the RGB data is on and which pixel clock, data enable, and syncs is used.

        Returns
        -------
        tuple[int,int,int,int]
            data_port, px_clock, data_enable, vhsync. See set_port_clock_definition doc for their definitions.
        """
        seq_byte = 243
        answer = self.send_command('r', seq_byte, 0x1A03, [])
        assert answer[2] == seq_byte, "received answer does not match command issued"
        data = answer[-1][0]
        data_port = data & 0x03
        px_clock = (data >> 2) & 0x03
        data_enable = (data >> 4) & 0x01
        vhsync = (data >> 5) & 0x01
        return data_port, px_clock, data_enable, vhsync

    def set_input_source(self, source:int=0, bitdepth:int=0):
        """
        Switch input source for the DMD. You can choose the parallel interface (HDMI/displayport/etc), flash memory, test, or a solid wall of light (a 'curtain').
        See page 35 of user guide.

        See also get_input_source

        Parameters
        ----------
        source : int, optional
            input source: 0 parallel, 1 internal tests, 2 Flash memory, 3 Solid curtain. by default 0
        bitdepth : int, optional
            Bit depth for the parallel interface, with: 0 30-bits, 1 24-bits, 2 20-bits, 3 16-bits, by default 0
        """
        payload = 0
        payload |= source & 0x07
        payload |= (bitdepth & 0x03) << 3
        self.send_command('w', 1, 0x1A00, [payload])

    def get_input_source(self) -> tuple[int,int]:
        """
        Read which input source is currently used.

        Returns
        -------
        tuple[int,int]
            source, bitdepth. See set_input_source doc for their definitions.
        """
        seq_byte = 112
        answer = self.send_command('r', seq_byte, 0x1A00, [])
        assert answer[2] == seq_byte, "received answer does not match command issued"
        data = answer[-1][0]
        source = data & 0x07
        bitdepth = (data >> 3) & 0x03
        return source, bitdepth

    def lock_displayport(self):
        """
        Lock external source over DisplayPort connection. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[2])
        self.set_input_source()
    
    def lock_hdmi(self):
        """
        Lock external source over HDMI connection. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[1])
        self.set_input_source()

    def lock_release(self):
        """
        Remove lock to external source. 
        See page 40/41 of user guide.
        """
        # Power up DisplayPort
        self.send_command('w',0,0x1A01,[0])
        self.set_input_source()

    def get_source_lock(self) -> int:
        """Check if the source is locked, and if yes, via HDMI or DisplayPort. Returns 0 if not locked, 1 if HDMI, 2 if DisplayPort."""
        locked = self.get_main_status()[3]
        if locked:
            port = self.send_command('r',0,0x1A01,[])
            return port[-1][0]
        else:
            return 0

#### Test pattern, load image, and curtain definitions

    def select_test_pattern(self,pattern:int):
        """
        Select the test pattern. 0 = Solid field, 1 = Horizontal ramp, 2 = Vertical ramp, 3 = Horizontal lines, 4 = Diagonal lines, 5 = Vertical lines, 6 = Grid, 7 = Checkerboard, 8 = RGB ramp, 9 = Color bars, 10 = No pattern
        """
        assert pattern < 11, "Pattern must be int between 0 and 10"
        self.send_command('w',0,0x1203,[pattern])
    
    def set_test_pattern_colors(self, foreground:tuple[int,int,int], background:tuple[int,int,int]):
        """
        Set test pattern fore- and background.

        Parameters
        ----------
        foreground : tuple[int,int,int]
            RGB intensities of foreground, with each color an int between 0 and 1023
        background : tuple[int,int,int]
            RGB intensities of background, with each color an int between 0 and 1023
        """
        byte10 = bits_to_bytes(number_to_bits(foreground[0],10))
        byte32 = bits_to_bytes(number_to_bits(foreground[1],10))
        byte54 = bits_to_bytes(number_to_bits(foreground[2],10))
        byte76 = bits_to_bytes(number_to_bits(background[0],10))
        byte98 = bits_to_bytes(number_to_bits(background[1],10))
        byte1110 = bits_to_bytes(number_to_bits(background[2],10))
        payload = byte10 + byte32 + byte54 + byte76 + byte98 + byte1110
        self.send_command('w',0,0x1204,payload)

    def set_curtain_color(self, color:tuple[int,int,int]=(0,0,0)):
        """
        Set curtain color, manual section 2.3.1.4.

        Parameters
        ----------
        color : tuple[int,int,int]
            RGB intensities of the curtain, with each color an int between 0 and 1023. Defaults to (0,0,0) - a black curtain.
        """        
        byte10 = bits_to_bytes(number_to_bits(color[0],10))
        byte32 = bits_to_bytes(number_to_bits(color[1],10))
        byte54 = bits_to_bytes(number_to_bits(color[2],10))
        payload = byte10 + byte32 + byte54
        self.send_command('w',0,0x1100,payload)

    def load_image(self, image_index:int):
        """Load an image from the flash memory and display it. Load data into the flash memory using the upload_image function."""
        self.send_command('w',0x00,0x1A39,[image_index])

### Image flips (section 2.3.4)

    def set_flip_longaxis(self,flip:bool):
        """Flip image along the long axis"""
        self.send_command('w',0,0x1008,[flip])

    def get_flip_longaxis(self) -> bool:
        """Check whether image is flipped along the long axis"""
        answer = self.send_command('r',0,0x1008)
        return answer[-1][0] > 0

    def set_flip_shortaxis(self,flip:bool):
        """Flip image along the short axis"""
        self.send_command('w',0,0x1009,[flip])

    def get_flip_shortaxis(self) -> bool:
        """Check whether image is flipped along the short axis"""
        answer = self.send_command('r',0,0x1009)
        return answer[-1][0] > 0

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
        try:
            new_display_mode = self.get_display_mode()
        except IndexError:
            # random error sometimes, just go again, no idea why...
            new_display_mode = self.get_display_mode()
        if new_display_mode != mode:
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
        self.current_mode = self.display_modes_inv[ans[-1][0]]
        return self.current_mode
    
    def get_display_resolution(self) -> tuple[int,int,int,int,int,int,int,int]:
        """
        Get the display resolution, both of the input and outputted image. Very likely you are looking for index 2 and 3 (vertical and horizontal resolution) of what is returned.

        Returns
        -------
        A tuple with the following content:
            0. Input image, first active pixel (column) of cropped area
            1. Input image, first active line (row) of cropped area
            2. Input image horizontal resolution, pixels (columns) per line (row) of cropped area
            3. Input image vertical resolution, lines (rows) per frame of cropped area
            4. Output image, first active pixel (column) of displayed image
            5. Output image, first active line (row) of displayed image
            6. Output image horizontal resolution, pixels (columns) per line (row)
            7. Output image vertical resolution, lines (rows) per frame
        """
        reply = self.send_command('r',12,0x1000,[])
        ans = reply[-1]
        input_fac = list_to_int(ans[0:2])
        input_fal = list_to_int(ans[2:4])
        input_hr = list_to_int(ans[4:6])
        input_vr = list_to_int(ans[6:8])
        output_fac = list_to_int(ans[8:10])
        output_fal = list_to_int(ans[10:12])
        output_hr = list_to_int(ans[12:14])
        output_vr = list_to_int(ans[14:16])
        return (input_fac,input_fal,input_hr,input_vr,output_fac,output_fal,output_hr,output_vr)

### functions for setting Pattern Display (and LUT) (section 2.4.4.3)

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

    def configure_pattern_from_LUT(self, nr_of_LUT_entries:int = 1, nr_of_patterns_to_display:int = 0):
        """
        Pattern Display LUT Configuration: Configure displaying patterns from the Look Up Table (LUT), as added in setup_pattern_LUT_definition function. Start at 0, and go through nr_of_LUT_entries. Display a total of nr_of_patterns_to_display. If nr_of_patterns_to_display is set to zero, repeat indefinitly. Use start_pattern to actually start.
        See section 2.4.4.3.3 

        Parameters
        ----------
        nr_of_LUT_entries : int, optional
            _description_, by default 1
        nr_of_patterns_to_display : int, optional
            _description_, by default 0
        """
        byte_01 = bits_to_bytes(number_to_bits(nr_of_LUT_entries,10))
        byte_25 = bits_to_bytes(number_to_bits(nr_of_patterns_to_display,32))
        payload = byte_01 + byte_25
        self.send_command('w', 1 ,0x1A31, payload)

    def setup_pattern_LUT_definition(self, pattern_index:int = 0, disable_pattern_2_trigger_out:bool = False, extended_bit_depth:bool = False, exposuretime:int = 15000, darktime:int = 0, color:int = 1, bitdepth:int = 8, image_pattern_index:int = 0, bit_position:int = 0):
        """
        Add a pattern to the Look Up Table (LUT), see section 2.4.4.3.5. To actually use this, you also need to set Pattern Display LUT Configuration
        
        Parameters
        ----------
        pattern_index : int, optional, defaults to 0
            location in memory to store pattern, should be between 0 and 399.
        disable_pattern_2_trigger_out: bool, defauts False
            Whether to disable trigger 2 output for this pattern
        extended_bit_depth : bool, defaults False
            Whether to enable the extended bit depth
        exposuretime : int, optional, in µs
            on-time of led in a 60hz period flash, by default 15000 µs
        darktime : int, optional, in µs
            off-time of led in a 60hz period flash, by default 0 µs
        color : int, optional
            What color channel to display, with 0: none, 1: red, 2: green, 3: red & green, 4: blue, 5: blue+red, 6: blue+green, 7: red+green+blue, by default "1"
        bitdepth : int, optional
            bitdepth of channel to concider, by default 8
        image_pattern_index : int, optional
            index of image pattern to use (if applicable), by default 0
        bit_position : int, optional
            Bit position in the image pattern (Frame in video pattern mode). Valid range 0-23. Defaults to 0.
        """
        disable_pattern_2_trigger_out,extended_bit_depth = int(disable_pattern_2_trigger_out),int(extended_bit_depth)
        clear_after_exposure, wait_for_trigger = 0,0
        
        pattern_index_bytes = [(pattern_index & 0xFF), ((pattern_index >> 8) & 0xFF)]
        exposuretime_bytes = [(exposuretime & 0xFF), ((exposuretime >> 8) & 0xFF), ((exposuretime >> 16) & 0xFF)]
        
        byte_5 = 0
        byte_5 |= clear_after_exposure & 0x01
        byte_5 |= (bitdepth-1) & 0x07 << 1
        byte_5 |= (color) & 0x07 << 4
        byte_5 |= (wait_for_trigger) & 0x01 << 7
    
        darktime_bytes = [(darktime & 0xFF), ((darktime >> 8) & 0xFF), ((darktime >> 16) & 0xFF)]
        
        byte_9 = 0
        byte_9 |= disable_pattern_2_trigger_out & 0x01
        byte_9 |= (extended_bit_depth) & 0x01 << 1
        
        image_pattern_index_bytes = [(image_pattern_index & 0xFF), ((image_pattern_index >> 8) & 0xFF)]
        bit_postion_byte = (bit_position & 0x1F) << 3
        byte_10_11 = [image_pattern_index_bytes[0], (image_pattern_index_bytes[1] | bit_postion_byte)]
        payload = pattern_index_bytes + exposuretime_bytes + [byte_5] + darktime_bytes + [byte_9] + byte_10_11
        self.send_command('w', 1, 0x1A34, payload)

### Upload functions for images (section 2.4.4.4)

    def initialize_pattern_bmp_load(self, image_index:int, n_bytes:int, controller:int=0):
        """
        Initialize the upload of a bmp image to the device. Follow this command with pattern_bmp_load for the actual upload.
        
        Parameters
        ----------
        image_index : int
            Index of the uploaded image, between 0 and 17. Note that you can only upload in reversed order, so 3 before 2 before 1 before 0.
        n_bytes : int
            Number of bytes in the compressed image *including* the 48 byte header.
        controller : int
            If your DMD has 2 controllers (not always the case), decide to which one to send; 0 or 1. Defaults to 0.
        """
        byte0 = bits_to_bytes(number_to_bits(image_index,4))
        byte1 = [0]
        byte_rest =bits_to_bytes(number_to_bits(n_bytes,31))
        payload = byte0 + byte1 + byte_rest
        if controller == 0:
            command = 0x1A2A
        elif controller == 1:
            command = 0x1A2C
        else:
            raise ValueError(f"{controller} is not a valid controller, select 0 or 1")
        self.send_command('w', 0, command, payload)

    def pattern_bmp_load(self, encoded_image:bytearray, controller:int=0):
        """
        Upload an encoded bmp image to the internal memory in the device. Only use this function *after* initialize_pattern_bmp_load. On first call, 48-byte header + 456 bytes data, and then run this repeatedly with a max 504 byte payload (excluding 2 bytes to set the size of the payload).

        Parameters
        ----------
        image : PIL.Image.Image
            The image to upload, as a Pillow Image. Note that we convert everything to 8-bit grayscale images before compression, so any other information is trashed.
        controller : int
            If your DMD has 2 controllers (not always the case), decide to which one to send; 0 or 1. Defaults to 0.
        Additional Notes
        ----------------
        The image needs to be (1) compressed before sending using ERLE, (2) needs a header, and (3) be small enough for one send command. Chain multiple together for bigger uploads.
        """
        nr_of_bytes = len(encoded_image)
        bytes01 = bits_to_bytes(number_to_bits(nr_of_bytes,10))
        if nr_of_bytes > 510:
            raise DMDerror("Image cannot be uploaded: size too big. Make 504 byte chunks.")
        payload = bytes01 + list(encoded_image)
        if controller == 0:
            command = 0x1A2A
        elif controller == 1:
            command = 0x1A2D
        else:
            raise ValueError(f"{controller} is not a valid controller, select 0 or 1")
        self.send_command('w', 0, command, payload)

    def upload_image(self, image_index:int, image:Image.Image, dual_controller:bool=False):
        """
        Upload an image to the flash memory of the device.

        Parameters
        ----------
        image_index : int
            Index of the uploaded image, between 0 and 17. Note that you can only upload in reversed order, so 3 before 2 before 1 before 0.
        image : PIL.Image.Image
            The Image to upload, as a Pillow Image. Note that we convert everything to 8-bit grayscale images before compression, so any other information is trashed.
        dual_controller : bool
            If True, splits the image in half and uploads to both controllers (Primary and Secondary). Use when you have 2 controllers. Default is False.

        Additional Information
        ----------------------
        This is a convenience function combining initialize_pattern_bmp_load, the image compression, and pattern_bmp_load, so don't use those if you use this function! Check those functions for additional information. 
        The image needs to be compressed before sending, and needs a header, this is done using "Enhanced Run-Length Encoding", check erle.py for details.
        We split the image in 504 byte chunks, since that is also the size TI uses in the manual for their example (not clear why, I am sure this has very good reasons).
        """

        max_payload_size = 504
        first_payload_size = 504

        # Prepare a list of tasks: (controller_number, image_half_to_upload)
        upload_tasks = []

        if dual_controller:
            width, height = image.size
            half_width = width // 2
            # Create Left Half (for Controller 0)
            # Crop from (left, top, right, bottom)
            left_half = image.crop((0, 0, half_width, height))
            upload_tasks.append((0, left_half))

            # Create Right Half (for Controller 1)
            right_half = image.crop((half_width, 0, width, height))
            upload_tasks.append((1, right_half))
        else:
            # Single controller mode
            upload_tasks.append((0, image))

        # Process each controller with its specific image half
        for controller, img_half in upload_tasks:
            # First compress the image (-half)
            encoded_image = enhanced_rle_encode(img_half)

            # Calculate chunking stuff
            nr_of_bytes = len(encoded_image)
            encoded_image_l = list(encoded_image)

            # Calculation of number of loops required
            remainder = nr_of_bytes - first_payload_size
            if remainder < 0:
                nloops_required = 1
            else:
                nloops_required = math.ceil(remainder / max_payload_size) + 1

            # Break up the encoded image into chunks
            chunks = list()
            for i in range(nloops_required):
                if i == 0:
                    start = 0
                    end = first_payload_size
                elif i == nloops_required-1:
                    start = (i-1)*max_payload_size + first_payload_size
                    data = encoded_image_l[start:] # Take everything to end
                    chunks.append(data)
                    # We must continue here or the loop continues incorrectly!
                    continue 
                else:
                    start = (i-1)*max_payload_size + first_payload_size
                    end = start + max_payload_size
                data = encoded_image_l[start:end]
                chunks.append(data)

            # Initialize Load for this specific controller
            # This sends the Header + Size for the image at `image_index` to `controller`
            self.initialize_pattern_bmp_load(image_index, nr_of_bytes, controller=controller)

            # And Send the Actual Chunks of Data
            for i, chunk in enumerate(chunks):
                self.pattern_bmp_load(chunk, controller=controller)
                # TODO: loadbar?
                print(f'Controller {controller}: uploaded chunk {i+1}/{nloops_required}')
