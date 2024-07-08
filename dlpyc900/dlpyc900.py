import usb.core
import usb.util
import time
import numpy
import sys
from dlpyc900.erle import encode

def convlen(a:int|float,l:int) -> str:
    """
    Converts a number into a bit string of given length

    Parameters
    ----------
    a : int | float
        number
    l : int
        length of bitstring

    Returns
    -------
    str
        bitstring
    """
    b=bin(a)[2:]
    padding=l-len(b)
    b='0'*padding+b
    return b

def bitstobytes(a:str) -> bytes:
    """
    Convert a bit string into a given number of bytes

    Parameters
    ----------
    a : str
        bitstring (see convlen function)

    Returns
    -------
    bytes
        byte encoded bitstring.
    """
    bytelist=[]
    if len(a)%8!=0:
        padding=8-len(a)%8
        a='0'*padding+a
    for i in range(len(a)//8):
        bytelist.append(int(a[8*i:8*(i+1)],2))

    bytelist.reverse()

    return bytelist

# alternatives to the above. Better?
def bitstobytes2(bits: str) -> list[int]:
    """Convert a string of bits to a list of bytes."""
    return [int(bits[i:i+8], 2) for i in range(0, len(bits), 8)]

def convlen2(length: int, bitlen: int) -> str:
    """Convert length to a binary string of specified bit length."""
    return format(length, '0{}b'.format(bitlen))

def valid_n_bit(number : int, bits: int) -> bool:
    if type(number) != type(bits) != int:
        raise ValueError("Number and bits should be ints")
    if number < 0 or bits < 0:
        raise ValueError("Number and bits should be positive")
    return number < 2**bits

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
## standard usb command function

    def command(self,mode:str,sequencebyte:bytes,com1,com2,data=None):
        buffer = []

        flagstring=''
        if mode=='r':
            flagstring+='1'
        else:
            flagstring+='0'        
        flagstring+='1000000'
        buffer.append(bitstobytes(flagstring)[0])
        buffer.append(sequencebyte)
        temp=bitstobytes(convlen(len(data)+2,16))
        buffer.append(temp[0])
        buffer.append(temp[1])
        buffer.append(com2)
        buffer.append(com1)

        if len(buffer)+len(data)<65:
            for i in range(len(data)):
                buffer.append(data[i])
            for i in range(64-len(buffer)):
                buffer.append(0x00)
            self.dev.write(1, buffer)

        else:
            for i in range(64-len(buffer)):
                buffer.append(data[i])

            self.dev.write(1, buffer)

            buffer = []

            j=0
            while j<len(data)-58:
                buffer.append(data[j+58])
                j=j+1
                if j%64==0:
                    self.dev.write(1, buffer)
                    buffer = []

            if j%64!=0:
                while j%64!=0:
                    buffer.append(0x00)
                    j=j+1
                self.dev.write(1, buffer)                
        self.ans=self.dev.read(0x81,64)

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

        if mode == 'r':
            self.ans = self.dev.read(0x81, 64)

    def checkforerrors(self):
        """
        check for error reports in the dlp answer
        """
        self.command('r',0x22,0x01,0x00,[])
        if self.ans[6] != 0:
            print( self.ans[6] )

    def readreply(self):
        """Print the dlp answer"""
        for i in self.ans:
            print( hex(i) )

## function to lock source correctly (hopefully)
### See page 40 of userguide. maybe page 34 is also related, but not sure.
    def lock_displayport(self):
        # page 35? or page 40?
        # run command
        return 0
    
    def set_dual_pixel_mode(self):
        # page 35
        # option 2: Data Port 1-2, Dual Pixel mode. Even pixel on port 1, Odd pixel on port 2
        return 0
    
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
        command = 0x1A0A
        self.command('r', 0x00, command, [])
        mode = self.ans[6] & 0x03  # Extract bits 1:0 from the response byte.
        self.current_mode = self.display_modes[mode]
        return self.current_mode
    
## functions for setting video-pattern mode
# see page 73 in user guide

    def setup_videopattern(self, exposuretime:int = 15000, channel:str = "red", bitdepth:int = 8):
        """
        Settings for videopattern

        Parameters
        ----------
        exposuretime : int, optional
            on-time of led in a 60hz period flash, by default 15000 µs
        channel : str, optional
            what channel to display, by default "red"
        bitdepth : int, optional
            bitdepth of channel to concider, by default 8
        """
        if self.current_mode != 'video-pattern':
            raise ValueError("command can only be run in video-pattern mode.")
        # construct command p 73. 
        return 0

## functions for idle mode activation

    def idle_on(self):
        """Set DMD to idle mode"""
        self.command('w',0x00,0x02,0x01,[int('00000001',2)])
        self.checkforerrors()

    def idle_off(self):
        """Set DMD to active mode/deactivate idle mode"""
        self.command('w',0x00,0x02,0x01,[int('00000000',2)])
        self.checkforerrors()

## functions for power management

    def standby(self):
        """Set DMD to standby"""
        self.command('w',0x00,0x02,0x00,[int('00000001',2)])
        self.checkforerrors()

    def wakeup(self):
        """Set DMD to wakeup"""
        self.command('w',0x00,0x02,0x00,[int('00000000',2)])
        self.checkforerrors()

    def reset(self):
        """Reset DMD"""
        self.command('w',0x00,0x02,0x00,[int('00000010',2)])
        self.checkforerrors()

## test write and read operations, as reported in the dlpc900 programmer's guide

    def testread(self):
        self.command('r',0xff,0x11,0x00,[])
        self.readreply()

    def testwrite(self):
        self.command('w',0x22,0x11,0x00,[0xff,0x01,0xff,0x01,0xff,0x01])
        self.checkforerrors()

## some self explaining functions

    def changemode(self,mode):
        self.command('w',0x00,0x1a,0x1b,[mode])
        self.checkforerrors()

    def startsequence(self):
        self.command('w',0x00,0x1a,0x24,[2])
        self.checkforerrors()

    def pausesequence(self):
        self.command('w',0x00,0x1a,0x24,[1])
        self.checkforerrors()

    def stopsequence(self):
        self.command('w',0x00,0x1a,0x24,[0])
        self.checkforerrors()


    def configurelut(self,imgnum,repeatnum):
        img=convlen(imgnum,11)
        repeat=convlen(repeatnum,32)

        string=repeat+'00000'+img

        bytes=bitstobytes(string)

        self.command('w',0x00,0x1a,0x31,bytes)
        self.checkforerrors()
        

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



        self.command('w',0x00,0x1a,0x34,payload)
        self.checkforerrors()
        

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
        
        self.command('w',0x00,0x1a,0x2a,payload)
        self.checkforerrors()

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
            self.command('w',0x11,0x1a,0x2b,payload)


            self.checkforerrors()


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