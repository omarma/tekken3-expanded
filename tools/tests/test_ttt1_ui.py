"""Synthetic interface pack checks; no copyrighted fixtures required."""
import sys,struct,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ttt1'))
from PIL import Image
import ui

class Ttt1UiTests(unittest.TestCase):
    def test_portrait_palette_bands_and_transparency(self):
        im=Image.new('RGBA',(168,252),(0,0,0,0))
        for y,color in zip(range(0,252,64),('red','green','blue','white')):
            im.paste(color,(0,y,84,min(y+64,252)))
        tim=ui.ps1_tim(im,True)
        self.assertEqual(len(tim),544+126*252)
        self.assertEqual(struct.unpack_from('<HH',tim,540),(63,252))
        for y in range(252):
            pixels=tim[544+y*126:544+(y+1)*126]
            self.assertTrue(all(0<p<64 for p in pixels[:63]))
            self.assertEqual(pixels[63:],bytes(63))
        self.assertEqual([struct.unpack_from('<H',tim,20+i*128)[0] for i in range(4)],[0]*4)

    def test_icons_keep_requested_height(self):
        for height in (29,34,58,68):
            tim=ui.ps1_tim(Image.new('RGBA',(44,height),'red'))
            self.assertEqual(struct.unpack_from('<HH',tim,540),(16,height))
            self.assertEqual(len(tim),544+32*height)

    def test_pack_matches_the_runtime_layout(self):
        images={name:Image.new('RGBA',(w,h),'red') for name,w,h,_ in ui.SPECS}
        blob,tims=ui.pack(images)
        magic,version,count,size=struct.unpack_from('<4I',blob,0)
        self.assertEqual((magic,version,count,size),(0x3149554a,1,5,len(blob)))
        widths,heights=(126,32,32,32,32),(252,68,58,34,29)
        for i,tim in enumerate(tims):
            offset,length=struct.unpack_from('<2I',blob,16+i*8)
            self.assertEqual(blob[offset:offset+length],tim)
            self.assertEqual(length,544+widths[i]*heights[i])       # src/tekken3_ttt1_roster.c load_ui

if __name__=='__main__':unittest.main()
