; ============================================================
;  BiliCrawler（B站视频采集下载器）安装包脚本
;  用 NSIS 3.x 编译：makensis setup.nsi
; ============================================================

Unicode true

!define APP_NAME      "B站视频采集下载器"
!define APP_ID        "BiliCrawler"
!define APP_VERSION   "1.1.0"
!define APP_PUBLISHER "BiliCrawler"
!define APP_EXE       "BiliCrawler.exe"
!define APP_DESC      "B站公开数据采集与视频下载工具"
!define APP_WEB       ""

Name "${APP_NAME}"
OutFile "..\release\BiliCrawler-${APP_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP_ID}"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "1.1.0.0"
VIAddVersionKey /LANG=2052 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_DESC}"
VIAddVersionKey /LANG=2052 "FileVersion"     "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=2052 "LegalCopyright"  "个人学习用途，仅供非商业使用"
VIAddVersionKey /LANG=2052 "OriginalFilename" "${APP_ID}-${APP_VERSION}-Setup.exe"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON   "..\assets\app.ico"
!define MUI_UNICON "..\assets\app.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT  "本程序用于采集 B 站公开数据（视频信息 / 评论 / 弹幕）以及下载公开投稿视频，供个人学习与备份使用。$\r$\n$\r$\n同时会安装 FFmpeg，用于合并高清晰度视频的音视频轨。$\r$\n$\r$\n点击『下一步』继续。"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME ""
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------ 主程序
Section "主程序（必需）" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "..\dist\${APP_ID}\*.*"
  File "..\LICENSE.txt"

  ; 快捷方式
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  ; 卸载信息
  WriteRegStr   HKLM "Software\${APP_ID}" "InstallDir" "$INSTDIR"
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayName"     "${APP_NAME}"
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ------------------------------------------------------------ FFmpeg
Section "FFmpeg 音视频合并组件（推荐）" SEC_FFMPEG
  SetOutPath "$INSTDIR\ffmpeg\bin"
  File "..\assets\ffmpeg\bin\ffmpeg.exe"
SectionEnd

; ------------------------------------------------------------ 卸载
Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"

  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\ffmpeg"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\LICENSE.txt"
  RMDir /r "$INSTDIR"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
  DeleteRegKey HKLM "Software\${APP_ID}"

  ; 用户数据（Cookie）保留在 %LOCALAPPDATA%\BiliCrawler，不删除
SectionEnd

; ------------------------------------------------------------ 说明
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN}   "程序主体，包含运行所需的全部组件。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_FFMPEG} "FFmpeg 用于把高清晰度视频的画面与音轨合并为完整 MP4。不安装则只能下载低清晰度单文件。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ; 1) 命令行指定 /D= 时优先级最高，不覆盖
  ${GetParameters} $R0
  ${GetOptions} $R0 "/D=" $R1
  IfErrors 0 done

  ; 2) 已装过旧版本 → 沿用原目录，并提示是否先卸载
  ReadRegStr $R2 HKLM "Software\${APP_ID}" "InstallDir"
  IfFileExists "$R2\${APP_EXE}" 0 noOld
  StrCpy $INSTDIR $R2
  ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "UninstallString"
  StrCmp $0 "" done
  MessageBox MB_YESNO|MB_ICONQUESTION "检测到已安装 ${APP_NAME}。$\r$\n是否先卸载旧版本再继续安装？" IDNO done
  ExecWait '$0 /S _?=$INSTDIR'
  Goto done

  ; 3) 全新安装 → 默认装到 D 盘，无 D 盘则退回 Program Files
  noOld:
  IfFileExists "D:\*.*" 0 done
  StrCpy $INSTDIR "D:\Program Files\${APP_ID}"

  done:
FunctionEnd
