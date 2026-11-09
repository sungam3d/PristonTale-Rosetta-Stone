@echo off
rem ---------------------------------------------------------------------------
rem  Builds the release package:  ..\release\PT_RosettaStone_v<ver>\  + .zip
rem
rem    PT_RosettaStone.exe   - drag & drop converter window   (.NET Framework 4.8, ~100 KB,
rem    smd2ase.exe      - command line converter           runs on every Windows 10/11
rem                                                         with nothing to install)
rem    3dsMax\          - ASE importer/exporter for 3ds Max 2020+
rem    Blender\         - Blender 4.2+/5.x import/export extension zip
rem    Guide_3dsMax.html, Guide_Blender.html - user guides (+ Guide_images\), Forum_post.txt
rem    Source\          - all source code and build scripts
rem
rem  Optional:  build_release.cmd standalone
rem    also publishes a self-contained .NET 8 build (~70 MB single exe).
rem ---------------------------------------------------------------------------
setlocal
set VER=1.5.0
set ROOT=%~dp0..
set OUT=%ROOT%\release\PT_RosettaStone_v%VER%

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%\3dsMax" "%OUT%\Blender" "%OUT%\Guide_images" "%OUT%\Source" || goto :fail

dotnet build "%~dp0PT_SMD2ASE\PT_SMD2ASE.csproj" -c Release -f net48 -nologo -v q || goto :fail
dotnet build "%~dp0smd2ase\smd2ase.csproj" -c Release -f net48 -nologo -v q || goto :fail
copy /y "%~dp0PT_SMD2ASE\bin\Release\net48\PT_RosettaStone.exe" "%OUT%\" >nul || goto :fail
copy /y "%~dp0smd2ase\bin\Release\net48\smd2ase.exe" "%OUT%\" >nul || goto :fail

copy /y "%ROOT%\tools\max\PT_ASE_Importer.ms" "%OUT%\3dsMax\" >nul || goto :fail
copy /y "%ROOT%\tools\max\PT_ASE_Exporter.ms" "%OUT%\3dsMax\" >nul || goto :fail
copy /y "%ROOT%\tools\max\PT_ASE_Reader.cs"   "%OUT%\3dsMax\" >nul || goto :fail
copy /y "%ROOT%\tools\max\PT_ASE_Skin.cs"     "%OUT%\3dsMax\" >nul || goto :fail
python "%ROOT%\tools\build_blender_addon.py" || goto :fail
copy /y "%ROOT%\tools\dist\pt_ase_importer.zip" "%OUT%\Blender\" >nul || goto :fail
copy /y "%~dp0README_release.txt" "%OUT%\README.txt" >nul || goto :fail

rem guide
copy /y "%~dp0Guide\Guide_3dsMax.html" "%OUT%\" >nul || goto :fail
copy /y "%~dp0Guide\Guide_Blender.html" "%OUT%\" >nul || goto :fail
copy /y "%~dp0Forum_post.txt" "%OUT%\" >nul || goto :fail
xcopy /q /y "%~dp0Guide\Guide_images\*" "%OUT%\Guide_images\" >nul || goto :fail

rem source (no build output, caches or game data)
robocopy "%~dp0." "%OUT%\Source\src" /E /XD bin obj .vs __pycache__ /XF *.user *.suo >nul
if errorlevel 8 goto :fail
robocopy "%ROOT%\tools" "%OUT%\Source\tools" /E /XD dist __pycache__ /XF *.pyc >nul
if errorlevel 8 goto :fail
copy /y "%~dp0README_SOURCE.md" "%OUT%\Source\README_SOURCE.md" >nul || goto :fail
robocopy "%ROOT%\smdanim" "%OUT%\Source\smdanim" /E /XD __pycache__ /XF *.pyc >nul
if errorlevel 8 goto :fail
robocopy "%ROOT%\scripts" "%OUT%\Source\scripts" /E /XD __pycache__ /XF *.pyc >nul
if errorlevel 8 goto :fail
copy /y "%ROOT%\char2ase.py" "%OUT%\Source\char2ase.py" >nul || goto :fail
copy /y "%ROOT%\docs\TECHNICAL.md" "%OUT%\Source\TECHNICAL.md" >nul || goto :fail
copy /y "%ROOT%\LICENSE" "%OUT%\LICENSE.txt" >nul || goto :fail

if /i "%1"=="standalone" (
  dotnet publish "%~dp0PT_SMD2ASE\PT_SMD2ASE.csproj" -c Release -f net8.0-windows -r win-x64 --self-contained ^
    -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true ^
    -o "%ROOT%\release\standalone-net8" -nologo -v q || goto :fail
)

powershell -NoProfile -Command "Compress-Archive -Force -Path '%OUT%\*' -DestinationPath '%ROOT%\release\PT_RosettaStone_v%VER%.zip'" || goto :fail
echo.
echo Release ready: %OUT%
echo           zip: %ROOT%\release\PT_RosettaStone_v%VER%.zip
exit /b 0

:fail
echo BUILD FAILED
exit /b 1
