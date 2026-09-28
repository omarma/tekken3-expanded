// launcher_sdlcompat.h — thin SDL2/SDL3 shim for the handful of event and
// input symbols the launcher touches. Include AFTER launcher_platform.h (which
// pulls the correct SDL header). Lets backend/debug code use ONE spelling
// (the SDL3 names) on both builds, instead of scattering #if LNG_SDL3.

#ifndef LAUNCHER_NG_SDLCOMPAT_H
#define LAUNCHER_NG_SDLCOMPAT_H

#include "launcher_platform.h"   // SDL.h or SDL3/SDL.h

#if !defined(LNG_SDL3)
// ---- map SDL3 spellings onto SDL2 -----------------------------------------

// GL header (Android uses GLES; desktop SDL2 uses the system OpenGL header).
#if defined(__ANDROID__)
#include <SDL_opengles2.h>
#else
#include <SDL_opengl.h>
#endif

// Event type enum values
#define SDL_EVENT_QUIT                  SDL_QUIT
// SDL2 delivers window-close for a single-window app as SDL_QUIT, so map
// CLOSE_REQUESTED to an unused sentinel (never matches) to avoid a duplicate
// case against SDL_QUIT.
#define SDL_EVENT_WINDOW_CLOSE_REQUESTED 0x7FFFFFF0u
#define SDL_EVENT_KEY_DOWN              SDL_KEYDOWN
#define SDL_EVENT_KEY_UP                SDL_KEYUP
#define SDL_EVENT_MOUSE_MOTION          SDL_MOUSEMOTION
#define SDL_EVENT_MOUSE_BUTTON_DOWN     SDL_MOUSEBUTTONDOWN
#define SDL_EVENT_MOUSE_BUTTON_UP       SDL_MOUSEBUTTONUP
#define SDL_EVENT_MOUSE_WHEEL           SDL_MOUSEWHEEL
#define SDL_EVENT_GAMEPAD_BUTTON_DOWN   SDL_CONTROLLERBUTTONDOWN
#define SDL_EVENT_GAMEPAD_BUTTON_UP     SDL_CONTROLLERBUTTONUP
#define SDL_EVENT_GAMEPAD_AXIS_MOTION   SDL_CONTROLLERAXISMOTION
#define SDL_EVENT_JOYSTICK_BUTTON_DOWN  SDL_JOYBUTTONDOWN
#define SDL_EVENT_JOYSTICK_AXIS_MOTION  SDL_JOYAXISMOTION

// key event fields: SDL3 ev.key.{key,scancode,mod} == SDL2 ev.key.keysym.{sym,scancode,mod}
#define LNG_EVKEY(ev)    ((ev).key.keysym.sym)
#define LNG_EVSCAN(ev)   ((ev).key.keysym.scancode)
#define LNG_EVMOD(ev)    ((ev).key.keysym.mod)
// gamepad button event field: SDL3 ev.gbutton.button == SDL2 ev.cbutton.button
#define LNG_EVGBTN(ev)   ((ev).cbutton.button)
#define LNG_EVGBTNWHICH(ev) ((ev).cbutton.which)
// gamepad axis event fields: SDL3 ev.gaxis.{axis,value} == SDL2 ev.caxis.{axis,value}
#define LNG_EVGAXIS(ev)     ((ev).caxis.axis)
#define LNG_EVGAXISVAL(ev)  ((ev).caxis.value)
#define LNG_EVGAXISWHICH(ev) ((ev).caxis.which)
// raw joystick events (jbutton/jaxis field names are the same in SDL2/SDL3)
#define LNG_EVJBTN(ev)      ((ev).jbutton.button)
#define LNG_EVJBTNWHICH(ev) ((ev).jbutton.which)
#define LNG_EVJAXIS(ev)     ((ev).jaxis.axis)
#define LNG_EVJAXISVAL(ev)  ((ev).jaxis.value)
#define LNG_EVJAXISWHICH(ev) ((ev).jaxis.which)

// button->name lookup
#define SDL_GetGamepadStringForButton(b)  SDL_GameControllerGetStringForButton((SDL_GameControllerButton)(b))
// axis->name lookup
#define SDL_GetGamepadStringForAxis(a)    SDL_GameControllerGetStringForAxis((SDL_GameControllerAxis)(a))
typedef SDL_GameControllerButton  LNG_GamepadButton;
typedef SDL_GameControllerAxis    LNG_GamepadAxis;

// key-modifier masks (SDL3 renamed KMOD_* -> SDL_KMOD_*)
#define SDL_KMOD_CTRL   KMOD_CTRL
#define SDL_KMOD_ALT    KMOD_ALT
#define SDL_KMOD_SHIFT  KMOD_SHIFT

#else
// ---- native SDL3 ----------------------------------------------------------
#include <SDL3/SDL_opengl.h>
#define LNG_EVKEY(ev)    ((ev).key.key)
#define LNG_EVSCAN(ev)   ((ev).key.scancode)
#define LNG_EVMOD(ev)    ((ev).key.mod)
#define LNG_EVGBTN(ev)   ((ev).gbutton.button)
#define LNG_EVGBTNWHICH(ev) ((ev).gbutton.which)
#define LNG_EVGAXIS(ev)     ((ev).gaxis.axis)
#define LNG_EVGAXISVAL(ev)  ((ev).gaxis.value)
#define LNG_EVGAXISWHICH(ev) ((ev).gaxis.which)
#define LNG_EVJBTN(ev)      ((ev).jbutton.button)
#define LNG_EVJBTNWHICH(ev) ((ev).jbutton.which)
#define LNG_EVJAXIS(ev)     ((ev).jaxis.axis)
#define LNG_EVJAXISVAL(ev)  ((ev).jaxis.value)
#define LNG_EVJAXISWHICH(ev) ((ev).jaxis.which)
typedef SDL_GamepadButton  LNG_GamepadButton;
typedef SDL_GamepadAxis    LNG_GamepadAxis;
#endif

#endif // LAUNCHER_NG_SDLCOMPAT_H
