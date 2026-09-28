# Synthetic left-click at client coords (X,Y) inside the psx-runtime launcher
# window, then (optionally) screenshot the window client area to -Out.
# Coords are in the same space as shot_launcher.ps1's screenshot (client px).
param([int]$X = 0, [int]$Y = 0, [string]$Out = "")
$p = Get-Process psx-runtime -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "no window"; exit 1 }
$sig = @'
using System;
using System.Runtime.InteropServices;
public class C {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  public struct RECT { public int left, top, right, bottom; }
  public struct POINT { public int x, y; }
}
'@
Add-Type -TypeDefinition $sig 2>$null
$h = $p.MainWindowHandle
[C]::SetWindowPos($h, [IntPtr](-1), 0,0,0,0, 0x40 -bor 0x1 -bor 0x2) | Out-Null
[C]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 300
$tl = New-Object C+POINT
[C]::ClientToScreen($h, [ref]$tl) | Out-Null
$sx = $tl.x + $X; $sy = $tl.y + $Y
[C]::SetCursorPos($sx, $sy) | Out-Null
Start-Sleep -Milliseconds 80
[C]::mouse_event(0x0002, 0,0,0,[IntPtr]::Zero)  # LEFTDOWN
Start-Sleep -Milliseconds 50
[C]::mouse_event(0x0004, 0,0,0,[IntPtr]::Zero)  # LEFTUP
Write-Output ("clicked client (" + $X + "," + $Y + ") -> screen (" + $sx + "," + $sy + ")")
Start-Sleep -Milliseconds 250
if ($Out -ne "") {
  $r = New-Object C+RECT
  [C]::GetClientRect($h, [ref]$r) | Out-Null
  $tl2 = New-Object C+POINT
  [C]::ClientToScreen($h, [ref]$tl2) | Out-Null
  $w = $r.right - $r.left; $ht = $r.bottom - $r.top
  Add-Type -AssemblyName System.Drawing
  $bmp = New-Object System.Drawing.Bitmap($w, $ht)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($tl2.x, $tl2.y, 0, 0, (New-Object System.Drawing.Size($w, $ht)))
  $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Output ("saved " + $Out)
}
