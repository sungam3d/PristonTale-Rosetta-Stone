-- How fast can MAXScript key bone transforms?  (3dsmaxbatch speed probe)
resetMaxFile #noPrompt
(
local nb = 20, nk = 1000
local bones = #()
for i = 1 to nb do
(
    local b = Point name:("b" + i as string) size:2
    b.position.controller = Linear_Position()
    b.rotation.controller = Linear_Rotation()
    b.scale.controller = Linear_Scale()
    if i > 1 do b.parent = bones[i - 1]
    append bones b
)
local t = timestamp()
with redraw off
(
    undo off
    (
        with animate on
        (
            for b in bones do
                for k = 0 to nk - 1 do
                    at time (k * 1.0) b.transform = (rotateZMatrix (k * 0.5)) * (transMatrix [k * 0.01, 1, 2])
        )
    )
)
local dt = timestamp() - t
format "SPEED: % keys in % ms = % us/key\n" (nb * nk) dt (dt * 1000.0 / (nb * nk))
-- key-array route
t = timestamp()
local c = bones[1].position.controller
for k = 0 to nk - 1 do (local key = addNewKey c ((k * 1.0 + 0.5) as time); key.value = [k, 0, 0])
dt = timestamp() - t
format "ADDKEY: % keys in % ms\n" nk dt
-- execute literal parse speed
t = timestamp()
local s = stringStream ""
format "#(" to:s
for k = 1 to 20000 do format "(matrix3 [1,0,0] [0,1,0] [0,0,1] [%,2.5,3.25])," k to:s
format "0)" to:s
local arr = execute (s as string)
dt = timestamp() - t
format "EXECUTE: 20000 matrix3 literals in % ms\n" dt
)
