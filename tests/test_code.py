#%%
import dlpyc900.dlpyc900 as dlpyc900
import numpy
# import PIL.Image

#%% test reading some properties
dlp=dlpyc900.dmd()
print(dlp.get_display_mode())
print(dlp.ans)
print(dlpyc900.parse_reply(dlp.ans))

#%%
dlp.set_display_mode('pattern')


#%%

images=[]

images.append((numpy.asarray(PIL.Image.open("testimage.tif"))//129))

dlp=dlpyc900.dmd()

dlp.stopsequence()

dlp.changemode(3)

exposure=[1000000]*30
dark_time=[0]*30
trigger_in=[False]*30
trigger_out=[1]*30

dlp.defsequence(images,exposure,trigger_in,dark_time,trigger_out,0)

dlp.startsequence()
