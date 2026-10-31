// corridor key studio win32 standalone installer
#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IDI_APPICON 101
#define IDR_PAYLOAD 102

#define WM_INSTALL_PROGRESS (WM_USER + 1)
#define WM_INSTALL_LOG      (WM_USER + 2)
#define WM_INSTALL_FINISHED (WM_USER + 3)

#define IDC_BTN_INSTALL     1001
#define IDC_BTN_CANCEL      1002
#define IDC_BTN_BROWSE_INST 1003
#define IDC_BTN_BROWSE_WGT  1004
#define IDC_EDIT_INST       1005
#define IDC_EDIT_WGT        1006
#define IDC_CHK_SHORTCUT    1007
#define IDC_CHK_WEIGHTS     1008
#define IDC_CHK_LOWVRAM     1009
#define IDC_PROGRESS        1010
#define IDC_LOG             1011
#define IDC_STATUS          1012
#define IDC_SYSINFO         1013

static HWND g_hwnd = NULL;
static HWND g_hEditInst = NULL;
static HWND g_hEditWgt = NULL;
static HWND g_hBtnBrowse1 = NULL;
static HWND g_hBtnBrowse2 = NULL;
static HWND g_hChkShortcut = NULL;
static HWND g_hChkWeights = NULL;
static HWND g_hChkLowVram = NULL;
static HWND g_hProgress = NULL;
static HWND g_hLog = NULL;
static HWND g_hStatus = NULL;
static HWND g_hBtnInstall = NULL;
static HWND g_hBtnCancel = NULL;

static BOOL g_installed = FALSE;
static BOOL g_isExistingBuild = FALSE;
static WCHAR g_targetDir[MAX_PATH] = {0};
static WCHAR g_weightsDir[MAX_PATH] = {0};
static BOOL g_optShortcut = TRUE;
static BOOL g_optWeights = TRUE;
static BOOL g_optLowVram = TRUE;

static HBRUSH g_hbrBackground = NULL;
static HBRUSH g_hbrLogBox = NULL;
static HFONT g_hFontTitle = NULL;
static HFONT g_hFontNormal = NULL;
static HFONT g_hFontLog = NULL;

static void AppendLog(HWND hLog, const WCHAR* text) {
    int len = GetWindowTextLengthW(hLog);
    SendMessageW(hLog, EM_SETSEL, (WPARAM)len, (LPARAM)len);
    SendMessageW(hLog, EM_REPLACESEL, 0, (LPARAM)text);
    SendMessageW(hLog, EM_REPLACESEL, 0, (LPARAM)L"\r\n");
    SendMessageW(hLog, EM_SCROLLCARET, 0, 0);
}

static BOOL RunCommandPipe(const WCHAR* cmd, const WCHAR* workDir, HWND hwnd) {
    SECURITY_ATTRIBUTES sa = { sizeof(sa), NULL, TRUE };
    HANDLE hRead = NULL, hWrite = NULL;
    if (!CreatePipe(&hRead, &hWrite, &sa, 0)) return FALSE;
    SetHandleInformation(hRead, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW si = { sizeof(si) };
    si.dwFlags = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = hWrite;
    si.hStdError = hWrite;

    PROCESS_INFORMATION pi = {0};
    WCHAR cmdBuf[2048];
    wcscpy(cmdBuf, cmd);

    BOOL created = CreateProcessW(NULL, cmdBuf, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, workDir, &si, &pi);
    CloseHandle(hWrite);

    if (!created) {
        CloseHandle(hRead);
        return FALSE;
    }

    char buf[512];
    DWORD bytesRead = 0;
    while (ReadFile(hRead, buf, sizeof(buf) - 1, &bytesRead, NULL) && bytesRead > 0) {
        buf[bytesRead] = '\0';
        int wlen = MultiByteToWideChar(CP_OEMCP, 0, buf, -1, NULL, 0);
        if (wlen > 1) {
            WCHAR* wbuf = (WCHAR*)malloc(wlen * sizeof(WCHAR));
            if (wbuf) {
                MultiByteToWideChar(CP_OEMCP, 0, buf, -1, wbuf, wlen);
                // trim and post
                WCHAR* line = wbuf;
                WCHAR* nl = NULL;
                while ((nl = wcsstr(line, L"\n")) != NULL) {
                    *nl = L'\0';
                    if (nl > line && *(nl - 1) == L'\r') *(nl - 1) = L'\0';
                    if (wcslen(line) > 0) {
                        WCHAR* copy = _wcsdup(line);
                        PostMessageW(hwnd, WM_INSTALL_LOG, 0, (LPARAM)copy);
                    }
                    line = nl + 1;
                }
                if (wcslen(line) > 0) {
                    WCHAR* copy = _wcsdup(line);
                    PostMessageW(hwnd, WM_INSTALL_LOG, 0, (LPARAM)copy);
                }
                free(wbuf);
            }
        }
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD exitCode = 0;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    CloseHandle(hRead);

    return (exitCode == 0);
}

static BOOL ExtractResource(int resId, const WCHAR* outPath) {
    HRSRC hRes = FindResourceW(NULL, MAKEINTRESOURCEW(resId), (LPCWSTR)RT_RCDATA);
    if (!hRes) return FALSE;
    HGLOBAL hMem = LoadResource(NULL, hRes);
    if (!hMem) return FALSE;
    DWORD size = SizeofResource(NULL, hRes);
    void* pData = LockResource(hMem);
    if (!pData || size == 0) return FALSE;

    HANDLE hFile = CreateFileW(outPath, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile == INVALID_HANDLE_VALUE) return FALSE;

    DWORD written = 0;
    BOOL ok = WriteFile(hFile, pData, size, &written, NULL);
    CloseHandle(hFile);
    return ok;
}

static BOOL CreateShortcut(const WCHAR* targetPath, const WCHAR* shortcutPath, const WCHAR* iconPath, const WCHAR* desc) {
    IShellLinkW* psl = NULL;
    HRESULT hr = CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, &IID_IShellLinkW, (void**)&psl);
    if (SUCCEEDED(hr)) {
        IPersistFile* ppf = NULL;
        psl->lpVtbl->SetPath(psl, targetPath);
        psl->lpVtbl->SetDescription(psl, desc);
        WCHAR workDir[MAX_PATH];
        wcscpy(workDir, targetPath);
        PathRemoveFileSpecW(workDir);
        psl->lpVtbl->SetWorkingDirectory(psl, workDir);
        if (iconPath && PathFileExistsW(iconPath)) {
            psl->lpVtbl->SetIconLocation(psl, iconPath, 0);
        }
        hr = psl->lpVtbl->QueryInterface(psl, &IID_IPersistFile, (void**)&ppf);
        if (SUCCEEDED(hr)) {
            hr = ppf->lpVtbl->Save(ppf, shortcutPath, TRUE);
            ppf->lpVtbl->Release(ppf);
        }
        psl->lpVtbl->Release(psl);
    }
    return SUCCEEDED(hr);
}

static BOOL IsBuildInstalled(const WCHAR* targetDir) {
    if (!targetDir || wcslen(targetDir) == 0) return FALSE;
    WCHAR bat[MAX_PATH];
    WCHAR pkg[MAX_PATH];
    PathCombineW(bat, targetDir, L"launch_gui.bat");
    PathCombineW(pkg, targetDir, L"corridorkey");
    return (PathFileExistsW(bat) && PathFileExistsW(pkg));
}

static void UpdateBuildDetectionUI(void) {
    if (!g_hEditInst || !g_hBtnInstall || !g_hStatus) return;
    WCHAR target[MAX_PATH];
    GetWindowTextW(g_hEditInst, target, MAX_PATH);
    if (wcslen(target) == 0) return;

    if (!IsBuildInstalled(target)) {
        g_isExistingBuild = FALSE;
        SetWindowTextW(g_hBtnInstall, L"Install CorridorKey Studio");
        SetWindowTextW(g_hStatus, L"Ready to install.");
        SendMessageW(g_hChkWeights, BM_SETCHECK, BST_CHECKED, 0);
        return;
    }

    g_isExistingBuild = TRUE;
    SetWindowTextW(g_hBtnInstall, L"Update CorridorKey Studio");
    SetWindowTextW(g_hStatus, L"Existing build detected (branch app-win). Ready to update.");

    WCHAR wgtFile[MAX_PATH];
    WCHAR wgtDir[MAX_PATH];
    GetWindowTextW(g_hEditWgt, wgtDir, MAX_PATH);
    PathCombineW(wgtFile, wgtDir, L"corridorkey_v2.safetensors");
    if (PathFileExistsW(wgtFile)) {
        SendMessageW(g_hChkWeights, BM_SETCHECK, BST_UNCHECKED, 0);
    }
}

static DWORD WINAPI InstallThreadProc(LPVOID lpParam) {
    HWND hwnd = (HWND)lpParam;

    if (g_isExistingBuild) {
        PostMessageW(hwnd, WM_INSTALL_PROGRESS, 10, (LPARAM)L"Updating application files...");
        // 1. extract embedded payload zip to overwrite core files
        WCHAR tempZip[MAX_PATH];
        GetTempPathW(MAX_PATH, tempZip);
        PathAppendW(tempZip, L"corridorkey_payload.zip");

        if (ExtractResource(IDR_PAYLOAD, tempZip)) {
            WCHAR tarCmd[1024];
            wsprintfW(tarCmd, L"tar.exe -xf \"%s\" -C \"%s\"", tempZip, g_targetDir);
            if (!RunCommandPipe(tarCmd, g_targetDir, hwnd)) {
                WCHAR psCmd[2048];
                wsprintfW(psCmd, L"powershell.exe -NoProfile -Command \"Expand-Archive -Path '%s' -DestinationPath '%s' -Force\"", tempZip, g_targetDir);
                RunCommandPipe(psCmd, g_targetDir, hwnd);
            }
            DeleteFileW(tempZip);
        }

        // 2. verify python environment
        PostMessageW(hwnd, WM_INSTALL_PROGRESS, 50, (LPARAM)L"Verifying dependencies...");
        WCHAR venvDir[MAX_PATH];
        PathCombineW(venvDir, g_targetDir, L"venv");
        WCHAR pyVenvBin[MAX_PATH];
        PathCombineW(pyVenvBin, venvDir, L"Scripts\\python.exe");

        if (!PathFileExistsW(pyVenvBin)) {
            WCHAR venvCmd[1024];
            wsprintfW(venvCmd, L"uv.exe venv \"%s\"", venvDir);
            if (!RunCommandPipe(venvCmd, g_targetDir, hwnd)) {
                wsprintfW(venvCmd, L"py -3.12 -m venv \"%s\"", venvDir);
                if (!RunCommandPipe(venvCmd, g_targetDir, hwnd)) {
                    wsprintfW(venvCmd, L"python -m venv \"%s\"", venvDir);
                    RunCommandPipe(venvCmd, g_targetDir, hwnd);
                }
            }
        }

        // 3. fast dependency check
        WCHAR pipCmd[2048];
        WCHAR uvTest[256] = L"uv.exe --version";
        if (RunCommandPipe(uvTest, g_targetDir, hwnd)) {
            wsprintfW(pipCmd, L"uv.exe pip install -r requirements.txt PySide6 --python \"%s\"", pyVenvBin);
            RunCommandPipe(pipCmd, g_targetDir, hwnd);
        } else {
            WCHAR pipBin[MAX_PATH];
            PathCombineW(pipBin, venvDir, L"Scripts\\pip.exe");
            wsprintfW(pipCmd, L"\"%s\" install -r requirements.txt PySide6", pipBin);
            RunCommandPipe(pipCmd, g_targetDir, hwnd);
        }

        // 4. check weights - preserve if present
        WCHAR mainWeights[MAX_PATH];
        PathCombineW(mainWeights, g_weightsDir, L"corridorkey_v2.safetensors");
        if (PathFileExistsW(mainWeights)) {
            PostMessageW(hwnd, WM_INSTALL_PROGRESS, 80, (LPARAM)L"Foundation models verified.");
        } else if (g_optWeights) {
            PostMessageW(hwnd, WM_INSTALL_PROGRESS, 75, (LPARAM)L"Downloading foundation models (~5 GB)...");
            WCHAR dlCmd[1024];
            wsprintfW(dlCmd, L"\"%s\" scripts\\download_weights.py", pyVenvBin);
            RunCommandPipe(dlCmd, g_targetDir, hwnd);
        }

        // 5. refresh desktop shortcut
        if (g_optShortcut) {
            PostMessageW(hwnd, WM_INSTALL_PROGRESS, 92, (LPARAM)L"Refreshing desktop shortcut...");
            WCHAR deskPath[MAX_PATH];
            SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, deskPath);
            PathAppendW(deskPath, L"CorridorKey Studio.lnk");

            WCHAR targetBat[MAX_PATH];
            PathCombineW(targetBat, g_targetDir, L"launch_gui.bat");

            WCHAR iconFile[MAX_PATH];
            PathCombineW(iconFile, g_targetDir, L"installer\\icon.ico");
            if (!PathFileExistsW(iconFile)) {
                PathCombineW(iconFile, g_targetDir, L"gui\\icon.png");
            }

            CreateShortcut(targetBat, deskPath, iconFile, L"CorridorKey Studio");
        }

        PostMessageW(hwnd, WM_INSTALL_PROGRESS, 100, (LPARAM)L"Update Complete!");
        PostMessageW(hwnd, WM_INSTALL_FINISHED, 1, 0);
        return 0;
    }

    PostMessageW(hwnd, WM_INSTALL_PROGRESS, 5, (LPARAM)L"Preparing installation directory...");

    CreateDirectoryW(g_targetDir, NULL);
    CreateDirectoryW(g_weightsDir, NULL);

    // 1. extract embedded payload zip
    PostMessageW(hwnd, WM_INSTALL_PROGRESS, 10, (LPARAM)L"Extracting core files...");
    WCHAR tempZip[MAX_PATH];
    GetTempPathW(MAX_PATH, tempZip);
    PathAppendW(tempZip, L"corridorkey_payload.zip");

    if (ExtractResource(IDR_PAYLOAD, tempZip)) {
        // use tar.exe built into windows 10/11
        WCHAR tarCmd[1024];
        wsprintfW(tarCmd, L"tar.exe -xf \"%s\" -C \"%s\"", tempZip, g_targetDir);
        if (!RunCommandPipe(tarCmd, g_targetDir, hwnd)) {
            // fallback to powershell expand-archive
            WCHAR psCmd[2048];
            wsprintfW(psCmd, L"powershell.exe -NoProfile -Command \"Expand-Archive -Path '%s' -DestinationPath '%s' -Force\"", tempZip, g_targetDir);
            RunCommandPipe(psCmd, g_targetDir, hwnd);
        }
        DeleteFileW(tempZip);
    }

    // 2. python environment setup
    PostMessageW(hwnd, WM_INSTALL_PROGRESS, 25, (LPARAM)L"Setting up Python virtual environment...");
    WCHAR venvDir[MAX_PATH];
    PathCombineW(venvDir, g_targetDir, L"venv");
    WCHAR pyVenvBin[MAX_PATH];
    PathCombineW(pyVenvBin, venvDir, L"Scripts\\python.exe");

    if (!PathFileExistsW(pyVenvBin)) {
        // try uv first, fallback to py -3.12 or python
        WCHAR venvCmd[1024];
        wsprintfW(venvCmd, L"uv.exe venv \"%s\"", venvDir);
        if (!RunCommandPipe(venvCmd, g_targetDir, hwnd)) {
            wsprintfW(venvCmd, L"py -3.12 -m venv \"%s\"", venvDir);
            if (!RunCommandPipe(venvCmd, g_targetDir, hwnd)) {
                wsprintfW(venvCmd, L"python -m venv \"%s\"", venvDir);
                RunCommandPipe(venvCmd, g_targetDir, hwnd);
            }
        }
    }

    // 3. install pytorch cuda and requirements
    PostMessageW(hwnd, WM_INSTALL_PROGRESS, 50, (LPARAM)L"Installing PyTorch CUDA & dependencies...");
    WCHAR pipCmd[2048];
    // check if uv is in path
    WCHAR uvTest[256] = L"uv.exe --version";
    if (RunCommandPipe(uvTest, g_targetDir, hwnd)) {
        wsprintfW(pipCmd, L"uv.exe pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --python \"%s\"", pyVenvBin);
        RunCommandPipe(pipCmd, g_targetDir, hwnd);
        wsprintfW(pipCmd, L"uv.exe pip install -r requirements.txt PySide6 --python \"%s\"", pyVenvBin);
        RunCommandPipe(pipCmd, g_targetDir, hwnd);
    } else {
        WCHAR pipBin[MAX_PATH];
        PathCombineW(pipBin, venvDir, L"Scripts\\pip.exe");
        wsprintfW(pipCmd, L"\"%s\" install torch torchvision --index-url https://download.pytorch.org/whl/cu128", pipBin);
        RunCommandPipe(pipCmd, g_targetDir, hwnd);
        wsprintfW(pipCmd, L"\"%s\" install -r requirements.txt PySide6", pipBin);
        RunCommandPipe(pipCmd, g_targetDir, hwnd);
    }

    // 4. download foundation models
    if (g_optWeights) {
        PostMessageW(hwnd, WM_INSTALL_PROGRESS, 75, (LPARAM)L"Downloading foundation model weights (~5 GB)...");
        WCHAR dlCmd[1024];
        wsprintfW(dlCmd, L"\"%s\" scripts\\download_weights.py", pyVenvBin);
        RunCommandPipe(dlCmd, g_targetDir, hwnd);
    }

    // 5. desktop shortcut
    if (g_optShortcut) {
        PostMessageW(hwnd, WM_INSTALL_PROGRESS, 92, (LPARAM)L"Creating Desktop shortcut...");
        WCHAR deskPath[MAX_PATH];
        SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, deskPath);
        PathAppendW(deskPath, L"CorridorKey Studio.lnk");

        WCHAR targetBat[MAX_PATH];
        PathCombineW(targetBat, g_targetDir, L"launch_gui.bat");

        WCHAR iconFile[MAX_PATH];
        PathCombineW(iconFile, g_targetDir, L"installer\\icon.ico");
        if (!PathFileExistsW(iconFile)) {
            PathCombineW(iconFile, g_targetDir, L"gui\\icon.png");
        }

        CreateShortcut(targetBat, deskPath, iconFile, L"CorridorKey Studio");
    }

    PostMessageW(hwnd, WM_INSTALL_PROGRESS, 100, (LPARAM)L"Installation Complete!");
    PostMessageW(hwnd, WM_INSTALL_FINISHED, 1, 0);
    return 0;
}

static void BrowseFolder(HWND hwndParent, HWND hEdit) {
    BROWSEINFOW bi = {0};
    bi.hwndOwner = hwndParent;
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    LPITEMIDLIST pidl = SHBrowseForFolderW(&bi);
    if (pidl) {
        WCHAR path[MAX_PATH];
        if (SHGetPathFromIDListW(pidl, path)) {
            SetWindowTextW(hEdit, path);
        }
        CoTaskMemFree(pidl);
    }
}

static void DetectGpu(WCHAR* outGpu, int maxLen) {
    wcscpy(outGpu, L"NVIDIA GPU auto-detect");
    HKEY hKey;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000", 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        WCHAR desc[256];
        DWORD size = sizeof(desc);
        if (RegQueryValueExW(hKey, L"DriverDesc", NULL, NULL, (LPBYTE)desc, &size) == ERROR_SUCCESS) {
            wcsncpy(outGpu, desc, maxLen - 1);
            outGpu[maxLen - 1] = L'\0';
        }
        RegCloseKey(hKey);
    }
}

static void FindBestDriveWin(WCHAR* outDir, int maxLen, WCHAR* outRoot, double* outFreeGb) {
    WCHAR drives[512];
    DWORD len = GetLogicalDriveStringsW(512, drives);
    WCHAR bestRoot[4] = L"C:\\";
    ULARGE_INTEGER maxFree = {0};

    if (len > 0) {
        WCHAR* d = drives;
        while (*d) {
            UINT type = GetDriveTypeW(d);
            if (type == DRIVE_FIXED) {
                ULARGE_INTEGER freeBytes, totalBytes, totalFree;
                if (GetDiskFreeSpaceExW(d, &freeBytes, &totalBytes, &totalFree)) {
                    if (freeBytes.QuadPart > maxFree.QuadPart) {
                        maxFree = freeBytes;
                        wcsncpy(bestRoot, d, 3);
                        bestRoot[3] = L'\0';
                    }
                }
            }
            d += wcslen(d) + 1;
        }
    }

    if (outRoot) wcscpy(outRoot, bestRoot);
    if (outFreeGb) *outFreeGb = (double)maxFree.QuadPart / (1024.0 * 1024.0 * 1024.0);

    if (towupper(bestRoot[0]) == L'C') {
        SHGetFolderPathW(NULL, CSIDL_PROFILE, NULL, 0, outDir);
        PathAppendW(outDir, L"CorridorKey-Studio");
    } else {
        wsprintfW(outDir, L"%sCorridorKey-Studio", bestRoot);
    }
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_CREATE: {
            g_hbrBackground = CreateSolidBrush(RGB(20, 24, 30));
            g_hbrLogBox = CreateSolidBrush(RGB(13, 17, 23));

            g_hFontTitle = CreateFontW(19, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI");
            g_hFontNormal = CreateFontW(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI");
            g_hFontLog = CreateFontW(12, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, FIXED_PITCH | FF_MODERN, L"Consolas");

            // title
            HWND hTitle = CreateWindowExW(0, L"STATIC", L"CorridorKey Studio Installer", WS_CHILD | WS_VISIBLE, 18, 14, 450, 24, hwnd, NULL, NULL, NULL);
            SendMessageW(hTitle, WM_SETFONT, (WPARAM)g_hFontTitle, TRUE);

            // system info
            WCHAR gpuDesc[256];
            DetectGpu(gpuDesc, 256);
            WCHAR sysDesc[512];
            wsprintfW(sysDesc, L"Windows x64 | %s", gpuDesc);
            HWND hSys = CreateWindowExW(0, L"STATIC", sysDesc, WS_CHILD | WS_VISIBLE, 18, 40, 520, 18, hwnd, (HMENU)IDC_SYSINFO, NULL, NULL);
            SendMessageW(hSys, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            // group 1: target directories
            HWND hGrpDir = CreateWindowExW(0, L"BUTTON", L"Target Directories", WS_CHILD | WS_VISIBLE | BS_GROUPBOX, 18, 66, 540, 114, hwnd, NULL, NULL, NULL);
            SendMessageW(hGrpDir, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            WCHAR defaultInst[MAX_PATH];
            WCHAR bestRoot[4];
            double freeGb = 0.0;
            FindBestDriveWin(defaultInst, MAX_PATH, bestRoot, &freeGb);

            CreateWindowExW(0, L"STATIC", L"Installation Directory:", WS_CHILD | WS_VISIBLE, 30, 88, 180, 16, hwnd, NULL, NULL, NULL);

            g_hEditInst = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", defaultInst, WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 30, 106, 410, 22, hwnd, (HMENU)IDC_EDIT_INST, NULL, NULL);
            SendMessageW(g_hEditInst, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            g_hBtnBrowse1 = CreateWindowExW(0, L"BUTTON", L"Browse...", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 448, 105, 96, 24, hwnd, (HMENU)IDC_BTN_BROWSE_INST, NULL, NULL);
            SendMessageW(g_hBtnBrowse1, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            CreateWindowExW(0, L"STATIC", L"Weights & Cache Directory:", WS_CHILD | WS_VISIBLE, 30, 134, 180, 16, hwnd, NULL, NULL, NULL);
            WCHAR defaultWgt[MAX_PATH];
            wsprintfW(defaultWgt, L"%s\\weights", defaultInst);

            g_hEditWgt = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", defaultWgt, WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 30, 150, 410, 22, hwnd, (HMENU)IDC_EDIT_WGT, NULL, NULL);
            SendMessageW(g_hEditWgt, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            g_hBtnBrowse2 = CreateWindowExW(0, L"BUTTON", L"Browse...", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 448, 149, 96, 24, hwnd, (HMENU)IDC_BTN_BROWSE_WGT, NULL, NULL);
            SendMessageW(g_hBtnBrowse2, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            // group 2: preferences
            HWND hGrpOpt = CreateWindowExW(0, L"BUTTON", L"Preferences", WS_CHILD | WS_VISIBLE | BS_GROUPBOX, 18, 188, 540, 96, hwnd, NULL, NULL, NULL);
            SendMessageW(hGrpOpt, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            g_hChkShortcut = CreateWindowExW(0, L"BUTTON", L"Create Desktop & Application Menu Shortcut", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX, 30, 208, 480, 20, hwnd, (HMENU)IDC_CHK_SHORTCUT, NULL, NULL);
            SendMessageW(g_hChkShortcut, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);
            SendMessageW(g_hChkShortcut, BM_SETCHECK, BST_CHECKED, 0);

            g_hChkWeights = CreateWindowExW(0, L"BUTTON", L"Pre-download ~5 GB foundation models immediately", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX, 30, 232, 480, 20, hwnd, (HMENU)IDC_CHK_WEIGHTS, NULL, NULL);
            SendMessageW(g_hChkWeights, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);
            SendMessageW(g_hChkWeights, BM_SETCHECK, BST_CHECKED, 0);

            g_hChkLowVram = CreateWindowExW(0, L"BUTTON", L"Enable 4GB Low-VRAM safety mode by default", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX, 30, 256, 480, 20, hwnd, (HMENU)IDC_CHK_LOWVRAM, NULL, NULL);
            SendMessageW(g_hChkLowVram, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);
            SendMessageW(g_hChkLowVram, BM_SETCHECK, BST_CHECKED, 0);

            // status & progress
            g_hStatus = CreateWindowExW(0, L"STATIC", L"Ready to install.", WS_CHILD | WS_VISIBLE, 18, 292, 540, 18, hwnd, (HMENU)IDC_STATUS, NULL, NULL);
            SendMessageW(g_hStatus, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            g_hProgress = CreateWindowExW(0, PROGRESS_CLASSW, NULL, WS_CHILD | WS_VISIBLE | PBS_SMOOTH, 18, 312, 540, 16, hwnd, (HMENU)IDC_PROGRESS, NULL, NULL);
            SendMessageW(g_hProgress, PBM_SETRANGE32, 0, 100);
            SendMessageW(g_hProgress, PBM_SETPOS, 0, 0);

            // log box
            g_hLog = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL, 18, 336, 540, 100, hwnd, (HMENU)IDC_LOG, NULL, NULL);
            SendMessageW(g_hLog, WM_SETFONT, (WPARAM)g_hFontLog, TRUE);

            // buttons
            g_hBtnCancel = CreateWindowExW(0, L"BUTTON", L"Exit", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 330, 448, 100, 28, hwnd, (HMENU)IDC_BTN_CANCEL, NULL, NULL);
            SendMessageW(g_hBtnCancel, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            g_hBtnInstall = CreateWindowExW(0, L"BUTTON", L"Install CorridorKey Studio", WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON, 438, 448, 120, 28, hwnd, (HMENU)IDC_BTN_INSTALL, NULL, NULL);
            SendMessageW(g_hBtnInstall, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

            UpdateBuildDetectionUI();
            break;
        }

        case WM_CTLCOLORSTATIC: {
            HDC hdcStatic = (HDC)wParam;
            HWND hStatic = (HWND)lParam;
            SetBkMode(hdcStatic, TRANSPARENT);
            if (hStatic == g_hStatus) {
                SetTextColor(hdcStatic, g_installed ? RGB(61, 214, 140) : RGB(201, 209, 217));
            } else if (GetDlgCtrlID(hStatic) == IDC_SYSINFO) {
                SetTextColor(hdcStatic, RGB(139, 148, 158));
            } else {
                SetTextColor(hdcStatic, RGB(220, 226, 235));
            }
            return (LRESULT)g_hbrBackground;
        }

        case WM_CTLCOLOREDIT: {
            HDC hdcEdit = (HDC)wParam;
            HWND hEdit = (HWND)lParam;
            if (hEdit == g_hLog) {
                SetBkColor(hdcEdit, RGB(13, 17, 23));
                SetTextColor(hdcEdit, RGB(139, 148, 158));
                return (LRESULT)g_hbrLogBox;
            }
            break;
        }

        case WM_COMMAND: {
            if (HIWORD(wParam) == EN_CHANGE && LOWORD(wParam) == IDC_EDIT_INST) {
                UpdateBuildDetectionUI();
                break;
            }

            int wmId = LOWORD(wParam);
            if (wmId == IDC_BTN_CANCEL) {
                DestroyWindow(hwnd);
            } else if (wmId == IDC_BTN_BROWSE_INST) {
                BrowseFolder(hwnd, g_hEditInst);
                UpdateBuildDetectionUI();
            } else if (wmId == IDC_BTN_BROWSE_WGT) {
                BrowseFolder(hwnd, g_hEditWgt);
                UpdateBuildDetectionUI();
            } else if (wmId == IDC_BTN_INSTALL) {
                if (g_installed) {
                    // launch application
                    WCHAR launchBat[MAX_PATH];
                    PathCombineW(launchBat, g_targetDir, L"launch_gui.bat");
                    ShellExecuteW(NULL, L"open", launchBat, NULL, g_targetDir, SW_SHOW);
                    DestroyWindow(hwnd);
                    return 0;
                }

                GetWindowTextW(g_hEditInst, g_targetDir, MAX_PATH);
                GetWindowTextW(g_hEditWgt, g_weightsDir, MAX_PATH);
                g_optShortcut = (SendMessageW(g_hChkShortcut, BM_GETCHECK, 0, 0) == BST_CHECKED);
                g_optWeights = (SendMessageW(g_hChkWeights, BM_GETCHECK, 0, 0) == BST_CHECKED);
                g_optLowVram = (SendMessageW(g_hChkLowVram, BM_GETCHECK, 0, 0) == BST_CHECKED);

                EnableWindow(g_hBtnInstall, FALSE);
                EnableWindow(g_hBtnBrowse1, FALSE);
                EnableWindow(g_hBtnBrowse2, FALSE);
                EnableWindow(g_hEditInst, FALSE);
                EnableWindow(g_hEditWgt, FALSE);

                CreateThread(NULL, 0, InstallThreadProc, (LPVOID)hwnd, 0, NULL);
            }
            break;
        }

        case WM_INSTALL_PROGRESS: {
            int pct = (int)wParam;
            const WCHAR* statusMsg = (const WCHAR*)lParam;
            SendMessageW(g_hProgress, PBM_SETPOS, (WPARAM)pct, 0);
            if (statusMsg) {
                SetWindowTextW(g_hStatus, statusMsg);
            }
            break;
        }

        case WM_INSTALL_LOG: {
            WCHAR* logText = (WCHAR*)lParam;
            if (logText) {
                AppendLog(g_hLog, logText);
                free(logText);
            }
            break;
        }

        case WM_INSTALL_FINISHED: {
            g_installed = TRUE;
            EnableWindow(g_hBtnInstall, TRUE);
            SetWindowTextW(g_hBtnInstall, L"Launch CorridorKey Studio");
            SetWindowTextW(g_hStatus, L"Installation Complete!");
            InvalidateRect(g_hStatus, NULL, TRUE);
            break;
        }

        case WM_DESTROY: {
            if (g_hbrBackground) DeleteObject(g_hbrBackground);
            if (g_hbrLogBox) DeleteObject(g_hbrLogBox);
            if (g_hFontTitle) DeleteObject(g_hFontTitle);
            if (g_hFontNormal) DeleteObject(g_hFontNormal);
            if (g_hFontLog) DeleteObject(g_hFontLog);
            PostQuitMessage(0);
            break;
        }

        default:
            return DefWindowProcW(hwnd, msg, wParam, lParam);
    }
    return 0;
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPWSTR lpCmdLine, int nCmdShow) {
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);

    INITCOMMONCONTROLSEX icex;
    icex.dwSize = sizeof(icex);
    icex.dwICC = ICC_PROGRESS_CLASS | ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&icex);

    WNDCLASSEXW wc = {0};
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.hIcon = LoadIconW(hInstance, MAKEINTRESOURCEW(IDI_APPICON));
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = CreateSolidBrush(RGB(20, 24, 30));
    wc.lpszClassName = L"CorridorKeyStudioSetupClass";

    RegisterClassExW(&wc);

    int width = 590;
    int height = 525;
    int x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
    int y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;

    HWND hwnd = CreateWindowExW(
        0,
        L"CorridorKeyStudioSetupClass",
        L"CorridorKey Studio Setup",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        x, y, width, height,
        NULL, NULL, hInstance, NULL
    );

    if (!hwnd) return 1;

    ShowWindow(hwnd, nCmdShow);
    UpdateWindow(hwnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    CoUninitialize();
    return (int)msg.wParam;
}
