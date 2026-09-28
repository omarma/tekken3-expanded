"""One-time file selection, automatic setup, then direct launch on later opens."""
from pathlib import Path
import ctypes, json, os, queue, subprocess, sys, threading
sys.path.insert(0,str(Path(__file__).resolve().parent))
import setup_backend as backend

# Windows owns the worker tree so Cancel also stops compilers and MAME.
class ProcessJob:
    def __init__(self):
        self.handle=None
        if os.name!='nt':return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),
                      ('min_work',ctypes.c_size_t),('max_work',ctypes.c_size_t),('count',w.DWORD),
                      ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class Io(ctypes.Structure):
            _fields_=[(name,ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',Io),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                      ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
        k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        k.CloseHandle.argtypes=[w.HANDLE]
        self.kernel=k;self.handle=k.CreateJobObjectW(None,None)
        info=Extended();info.basic.flags=0x2000
        if not self.handle or not k.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise OSError('Could not create the setup process group.')
    def assign(self,process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
            raise OSError('Could not manage the setup process group.')
    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None

FONT='Segoe UI' if os.name=='nt' else 'Helvetica Neue' if sys.platform=='darwin' else 'DejaVu Sans'

def reveal(path):
    if os.name=='nt':os.startfile(str(path))
    else:subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)])

def gui(test_hook=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    class App:
        def __init__(self):
            self.window=tk.Tk();self.window.title('Tekken 3 — First setup')
            self.window.configure(bg='#11131b');self.window.resizable(False,False)
            self.job=None;self.process=None;self.events=queue.Queue();self.busy=False
            self.epoch=0;self.completed=False
            s=ttk.Style(self.window);s.theme_use('clam')
            s.configure('.',font=(FONT,10),background='#11131b',foreground='#ececf2')
            s.configure('TFrame',background='#11131b')
            s.configure('TLabel',background='#11131b',foreground='#ececf2')
            s.configure('Muted.TLabel',foreground='#a9adbd')
            s.configure('Title.TLabel',font=(FONT,25,'bold'))
            s.configure('TEntry',fieldbackground='#232735',foreground='#f4f4f7',padding=8)
            s.configure('TButton',background='#2d3242',foreground='#f4f4f7',padding=(14,8),borderwidth=0)
            s.map('TButton',background=[('active','#404758'),('disabled','#20232d')])
            s.configure('Play.TButton',background='#744bd7',font=(FONT,12,'bold'),padding=(20,12))
            s.map('Play.TButton',background=[('active','#8862e8'),('disabled','#393247')])
            s.configure('TCheckbutton',background='#11131b',foreground='#ececf2')
            s.map('TCheckbutton',background=[('active','#11131b')])
            s.configure('TProgressbar',background='#9775ea',troughcolor='#232735',borderwidth=0)
            root=ttk.Frame(self.window,padding=28);root.pack(fill='both',expand=True)
            ttk.Label(root,text='TEKKEN 3',style='Title.TLabel').pack(anchor='w')
            ttk.Label(root,text='Choose your files. We’ll take care of the setup.',style='Muted.TLabel').pack(anchor='w',pady=(4,22))
            saved=backend.load_json(backend.STATE/'last-inputs.json')
            self.disc=tk.StringVar(value=saved.get('disc',''))
            self.ttt=tk.StringVar(value=saved.get('ttt1',''))
            self.ttt1=tk.BooleanVar(value=saved.get('include_ttt1',saved.get('jun',True)))
            self.tekken3=tk.StringVar(value=saved.get('tekken3',''))
            self.jin_red=tk.BooleanVar(value=saved.get('jin_red',False))
            self.controls=[];self.ttt1_controls=[]
            self.file_row(root,'Tekken 3 · USA PlayStation disc',self.disc,[('Disc image','*.cue *.bin *.iso')])
            self.check=ttk.Checkbutton(root,text='Include the TTT1 characters',variable=self.ttt1,command=self.update_ttt1)
            self.check.pack(anchor='w',pady=(18,6));self.controls.append(self.check)
            self.file_row(root,'TTT1 arcade · tektagt.zip',self.ttt,[('Arcade ZIP','*.zip')],ttt1=True)
            self.file_row(root,'Tekken 3 arcade · tekken3.zip (optional: arcade difficulty levels)',self.tekken3,[('Arcade ZIP','*.zip')],ttt1=True)
            self.jin_check=ttk.Checkbutton(root,text="Add-on: Jin's red lightning (from your TTT1 ROM)",variable=self.jin_red)
            self.jin_check.pack(anchor='w',pady=(6,0));self.controls.append(self.jin_check);self.ttt1_controls.append(self.jin_check)
            ttk.Label(root,text='Use your own game files. Nothing is uploaded.\n'+('Tools download automatically; ' if os.name=='nt' else 'Needs cmake, ninja, SDL3 and MAME (brew install cmake ninja sdl3 mame); ')
                      +'the first setup with the TTT1 characters takes about an hour.',
                      style='Muted.TLabel',justify='left').pack(anchor='w',pady=(12,20))
            self.status=tk.StringVar(value='Ready to set up')
            self.detail=tk.StringVar(value='No Python, MAME or compiler installation needed.' if os.name=='nt' else 'Your files stay on this Mac.')
            ttk.Label(root,textvariable=self.status,font=(FONT,11,'bold'),wraplength=585).pack(anchor='w')
            ttk.Label(root,textvariable=self.detail,style='Muted.TLabel',wraplength=585,justify='left').pack(anchor='w',pady=(5,10))
            self.progress=ttk.Progressbar(root,mode='indeterminate',length=590);self.progress.pack(fill='x',pady=(0,16))
            actions=ttk.Frame(root);actions.pack(fill='x')
            self.primary=ttk.Button(actions,text='Set up & play',style='Play.TButton',command=self.start)
            self.primary.pack(side='right')
            self.cancel_button=ttk.Button(actions,text='Cancel',command=self.cancel,state='disabled')
            self.cancel_button.pack(side='right',padx=(0,9))
            ttk.Button(actions,text='Open setup log',command=self.open_log).pack(side='left')
            self.window.protocol('WM_DELETE_WINDOW',self.close)
            self.update_ttt1();self.window.after(100,self.poll)
            self.window.update_idletasks()
            width=self.window.winfo_reqwidth();height=self.window.winfo_reqheight()
            x=max(0,(self.window.winfo_screenwidth()-width)//2);y=max(0,(self.window.winfo_screenheight()-height)//2)
            self.window.geometry(f'+{x}+{y}')
        def file_row(self,parent,label,value,types,ttt1=False):
            frame=ttk.Frame(parent);frame.pack(fill='x',pady=(0,9))
            ttk.Label(frame,text=label).pack(anchor='w',pady=(0,5))
            row=ttk.Frame(frame);row.pack(fill='x')
            entry=ttk.Entry(row,textvariable=value,width=58);entry.pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='Browse',command=lambda:self.browse(value,types))
            button.pack(side='right',padx=(9,0))
            self.controls.extend((entry,button))
            if ttt1:self.ttt1_controls.extend((entry,button))
        def browse(self,value,types):
            selected=filedialog.askopenfilename(parent=self.window,title='Choose your game file',filetypes=types)
            if selected:
                value.set(selected)
                folder=Path(selected).parent
                if not self.ttt.get() and (folder/'tektagt.zip').is_file():self.ttt.set(str(folder/'tektagt.zip'))
                if not self.tekken3.get() and (folder/'tekken3.zip').is_file():self.tekken3.set(str(folder/'tekken3.zip'))
        def update_ttt1(self):
            for widget in self.ttt1_controls:widget.configure(state='normal' if self.ttt1.get() and not self.busy else 'disabled')
        def set_busy(self,value):
            self.busy=value
            for widget in self.controls:widget.configure(state='disabled' if value else 'normal')
            self.update_ttt1();self.primary.configure(state='disabled' if value else 'normal')
            self.cancel_button.configure(state='normal' if value else 'disabled')
            if value:self.progress.start(12)
            else:self.progress.stop()
        def start(self):
            if not Path(self.disc.get()).is_file():self.detail.set('Choose your Tekken 3 USA disc image first.');return
            if self.ttt1.get() and not Path(self.ttt.get()).is_file():
                self.detail.set('Choose your TTT1 arcade ZIP, or turn off Include the TTT1 characters.');return
            if self.ttt1.get() and self.tekken3.get() and not Path(self.tekken3.get()).is_file():
                self.detail.set('The Tekken 3 arcade ZIP was not found. Choose it again, or clear the field.');return
            self.status.set('Starting setup');self.detail.set('Checking your game files…');self.set_busy(True)
            self.epoch+=1;epoch=self.epoch;self.completed=False
            python=Path(sys.executable).with_name('python.exe') if os.name=='nt' else Path(sys.executable)
            command=[str(python),'-I',str(backend.ROOT/'launcher/setup_backend.py'),'--disc',self.disc.get(),'--wait-for-parent']
            if self.ttt1.get():
                command+=['--ttt1',self.ttt.get()]
                if self.tekken3.get():command+=['--tekken3',self.tekken3.get()]
                if self.jin_red.get():command.append('--jin-red-lightning')
            else:command+=['--no-ttt1']
            try:
                self.job=ProcessJob()
                self.process=subprocess.Popen(command,cwd=backend.ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.job.assign(self.process)
                self.process.stdin.write('START\n');self.process.stdin.flush();self.process.stdin.close()
                threading.Thread(target=self.read_events,args=(self.process,epoch),daemon=True).start()
            except Exception as error:
                self.cancel();self.status.set('Setup could not start');self.detail.set(str(error))
        def read_events(self,process,epoch):
            for line in process.stdout:
                try:self.events.put((epoch,json.loads(line)))
                except ValueError:backend.log_line(line.rstrip())
            self.events.put((epoch,{'event':'exit','code':process.wait()}))
        def poll(self):
            try:
                while True:
                    epoch,event=self.events.get_nowait()
                    if epoch!=self.epoch:continue
                    kind=event.get('event')
                    if event.get('message'):self.status.set(event['message'])
                    if event.get('detail'):self.detail.set(event['detail'])
                    if kind=='error':
                        self.detail.set(event.get('message','Setup stopped.'))
                        self.status.set('Setup needs attention');self.primary.configure(text='Try again');self.set_busy(False)
                    elif kind=='complete':self.completed=True
                    elif kind=='exit':
                        if self.job:self.job.close();self.job=None
                        self.process=None;self.set_busy(False)
                        if self.completed and event['code']==0:
                            try:backend.launch_game();self.window.destroy();return
                            except Exception as error:self.status.set('Could not launch the game');self.detail.set(str(error))
                        elif self.status.get()!='Setup needs attention':
                            self.status.set('Setup stopped');self.detail.set('Open the setup log for details, then click Try again.')
                        self.primary.configure(text='Try again')
            except queue.Empty:pass
            self.window.after(100,self.poll)
        def cancel(self):
            self.epoch+=1
            if self.job:self.job.close();self.job=None
            if self.process and self.process.poll() is None:self.process.terminate()
            self.process=None;self.set_busy(False)
            self.status.set('Setup cancelled');self.detail.set('Completed downloads are kept. You can try again whenever you’re ready.')
            self.primary.configure(text='Try again')
        def close(self):
            if self.busy:self.cancel()
            self.window.destroy()
        def open_log(self):
            path=backend.STATE/'setup.log'
            if path.is_file():reveal(path)
            else:self.detail.set('The log appears when setup starts.')
    app=App()
    if test_hook:test_hook(app)
    app.window.mainloop()

if __name__=='__main__':
    if os.name=='nt':
        try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError,OSError):pass
    try:
        if backend.ready():backend.launch_game(settings='--settings' in sys.argv)
        else:gui()
    except Exception as error:
        import tkinter as tk
        from tkinter import messagebox
        window=tk.Tk();window.withdraw();messagebox.showerror('Tekken 3',str(error));window.destroy()
