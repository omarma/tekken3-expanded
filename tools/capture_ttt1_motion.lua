local machine=manager.machine
local cpu=machine.devices[":maincpu"]
local space=cpu.spaces["program"]
local frame=0
local calls={}
local busy=false
local trace=assert(io.open("jun-motion-poses.csv","w"))
trace:write("tick,source,frame,channels,destination,pose\n")
jun_motion_taps={}
local function state(name) return cpu.state[name].value end
local function tap(address,value,mask)
    if busy then return end
    local pc=state("pc")
    if pc~=0x80105b8c and pc~=0x80105e30 then return end
    busy=true
    local sp=state("sp")
    if pc==0x80105b8c then
        calls[sp]={source=state("s1"),frame=state("fp"),dest=state("s5"),channels=space:read_u32(sp+0x774)}
    else
        local call=calls[sp]
        if call and call.channels>0 and call.channels<=57 then
            local values={}
            for i=0,call.channels-1 do table.insert(values,string.format("%04x",space:read_u16(call.dest+i*2))) end
            trace:write(string.format("%d,%08x,%d,%d,%08x,%s\n",frame,call.source,call.frame,call.channels,call.dest,table.concat(values," ")))
            calls[sp]=nil
        end
    end
    busy=false
end
jun_motion_subscription=emu.add_machine_frame_notifier(function()
    frame=frame+1
    if frame==5 then
        for _,alias in ipairs({0,0x80000000,0xa0000000}) do
            table.insert(jun_motion_taps,space:install_read_tap(alias+0x003fe000,alias+0x003fffff,"jun-motion-"..tostring(alias),tap))
        end
    end
    if frame==240 then
        for _,handle in ipairs(jun_motion_taps) do handle:remove() end
        trace:close()
        machine:exit()
    end
end)
