// corridor key studio linux native installer
#define _GNU_SOURCE
#include <gtk/gtk.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/statvfs.h>
#include <mntent.h>
#include <time.h>

#include "payload_data.h"

#define BUNDLED_COMMIT "cd81a4d"
#define BUNDLED_BRANCH "app-linux"

typedef enum {
    BUILD_NOT_INSTALLED = 0,
    BUILD_UP_TO_DATE,
    BUILD_UPDATE_AVAILABLE
} BuildState;

typedef struct {
    GtkWidget *window;
    GtkWidget *entry_install;
    GtkWidget *entry_weights;
    GtkWidget *lbl_space;
    GtkWidget *chk_shortcut;
    GtkWidget *chk_weights;
    GtkWidget *chk_lowvram;
    GtkWidget *progress_bar;
    GtkWidget *lbl_status;
    GtkWidget *text_log;
    GtkWidget *btn_install;
    GtkWidget *btn_cancel;
    gboolean installed;
    gboolean is_existing_build;
} AppWidgets;

static AppWidgets *g_app = NULL;

typedef struct {
    char *text;
} LogMsg;

typedef struct {
    double fraction;
    char *text;
} ProgressMsg;

static gboolean on_idle_log(gpointer user_data) {
    LogMsg *msg = (LogMsg *)user_data;
    if (g_app && g_app->text_log) {
        GtkTextBuffer *buf = gtk_text_view_get_buffer(GTK_TEXT_VIEW(g_app->text_log));
        GtkTextIter end;
        gtk_text_buffer_get_end_iter(buf, &end);
        gtk_text_buffer_insert(buf, &end, msg->text, -1);
        gtk_text_buffer_insert(buf, &end, "\n", -1);

        // scroll to end
        GtkTextMark *mark = gtk_text_buffer_create_mark(buf, NULL, &end, FALSE);
        gtk_text_view_scroll_to_mark(GTK_TEXT_VIEW(g_app->text_log), mark, 0.0, TRUE, 0.0, 1.0);
        gtk_text_buffer_delete_mark(buf, mark);
    }
    g_free(msg->text);
    g_free(msg);
    return FALSE;
}

static gboolean on_idle_progress(gpointer user_data) {
    ProgressMsg *msg = (ProgressMsg *)user_data;
    if (g_app) {
        if (g_app->progress_bar) {
            gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(g_app->progress_bar), msg->fraction);
        }
        if (g_app->lbl_status && msg->text) {
            gtk_label_set_text(GTK_LABEL(g_app->lbl_status), msg->text);
        }
    }
    if (msg->text) g_free(msg->text);
    g_free(msg);
    return FALSE;
}

static gboolean on_idle_finished(gpointer user_data) {
    gboolean success = GPOINTER_TO_INT(user_data);
    if (g_app) {
        gtk_widget_set_sensitive(g_app->btn_install, TRUE);
        if (success) {
            g_app->installed = TRUE;
            gtk_button_set_label(GTK_BUTTON(g_app->btn_install), "Launch CorridorKey Studio");
            if (g_app->is_existing_build) {
                gtk_label_set_markup(GTK_LABEL(g_app->lbl_status), "<span foreground='#3dd68c' weight='bold'>Update Complete!</span>");
            } else {
                gtk_label_set_markup(GTK_LABEL(g_app->lbl_status), "<span foreground='#3dd68c' weight='bold'>Installation Complete!</span>");
            }
        } else {
            gtk_label_set_markup(GTK_LABEL(g_app->lbl_status), "<span foreground='#ff5c5c' weight='bold'>Installation Failed</span>");
        }
    }
    return FALSE;
}

static void send_log(const char *text) {
    LogMsg *msg = g_new0(LogMsg, 1);
    msg->text = g_strdup(text);
    g_idle_add(on_idle_log, msg);
}

static void send_progress(double fraction, const char *text) {
    ProgressMsg *msg = g_new0(ProgressMsg, 1);
    msg->fraction = fraction;
    msg->text = text ? g_strdup(text) : NULL;
    g_idle_add(on_idle_progress, msg);
}

static int run_command_stream(const char *cmd, const char *cwd) {
    char full_cmd[2048];
    if (cwd) {
        snprintf(full_cmd, sizeof(full_cmd), "cd \"%s\" && %s 2>&1", cwd, cmd);
    } else {
        snprintf(full_cmd, sizeof(full_cmd), "%s 2>&1", cmd);
    }

    FILE *fp = popen(full_cmd, "r");
    if (!fp) return -1;

    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        size_t len = strlen(line);
        if (len > 0 && line[len - 1] == '\n') line[len - 1] = '\0';
        if (len > 1 && line[len - 2] == '\r') line[len - 2] = '\0';
        if (strlen(line) > 0) {
            send_log(line);
        }
    }

    int status = pclose(fp);
    return WEXITSTATUS(status);
}

static char *find_uv_binary(void) {
    const char *home = getenv("HOME");
    char path[1024];

    if (home) {
        snprintf(path, sizeof(path), "%s/.local/bin/uv", home);
        if (access(path, X_OK) == 0) return g_strdup(path);

        snprintf(path, sizeof(path), "%s/.cargo/bin/uv", home);
        if (access(path, X_OK) == 0) return g_strdup(path);
    }

    if (access("/usr/local/bin/uv", X_OK) == 0) return g_strdup("/usr/local/bin/uv");
    if (access("/usr/bin/uv", X_OK) == 0) return g_strdup("/usr/bin/uv");

    FILE *fp = popen("which uv 2>/dev/null", "r");
    if (fp) {
        char line[512];
        if (fgets(line, sizeof(line), fp)) {
            pclose(fp);
            size_t len = strlen(line);
            if (len > 0 && line[len - 1] == '\n') line[len - 1] = '\0';
            if (strlen(line) > 0 && access(line, X_OK) == 0) return g_strdup(line);
        } else {
            pclose(fp);
        }
    }
    return NULL;
}

static void create_desktop_shortcuts(const char *target_dir) {
    const char *home = getenv("HOME");
    if (!home) return;

    // determine desktop screen directory
    char desktop_dir[512];
    FILE *xdg_fp = popen("xdg-user-dir DESKTOP 2>/dev/null", "r");
    gboolean got_xdg = FALSE;
    if (xdg_fp) {
        if (fgets(desktop_dir, sizeof(desktop_dir), xdg_fp)) {
            size_t len = strlen(desktop_dir);
            if (len > 0 && desktop_dir[len - 1] == '\n') desktop_dir[len - 1] = '\0';
            if (strlen(desktop_dir) > 0 && desktop_dir[0] == '/') got_xdg = TRUE;
        }
        pclose(xdg_fp);
    }
    if (!got_xdg) {
        snprintf(desktop_dir, sizeof(desktop_dir), "%s/Desktop", home);
    }

    char apps_dir[512];
    snprintf(apps_dir, sizeof(apps_dir), "%s/.local/share/applications", home);

    char mkdir_cmd[1024];
    snprintf(mkdir_cmd, sizeof(mkdir_cmd), "mkdir -p \"%s\" \"%s\"", desktop_dir, apps_dir);
    system(mkdir_cmd);

    const char *dest_dirs[] = { desktop_dir, apps_dir };
    for (int i = 0; i < 2; i++) {
        char desk_path[1024];
        snprintf(desk_path, sizeof(desk_path), "%s/corridorkey-studio.desktop", dest_dirs[i]);
        FILE *df = fopen(desk_path, "w");
        if (df) {
            fprintf(df, "[Desktop Entry]\n");
            fprintf(df, "Version=1.0\n");
            fprintf(df, "Type=Application\n");
            fprintf(df, "Name=CorridorKey Studio\n");
            fprintf(df, "GenericName=Chroma Keying Suite\n");
            fprintf(df, "Comment=AI-powered green screen cutout tool for Blender\n");
            fprintf(df, "Exec=%s/launch_gui.sh\n", target_dir);
            fprintf(df, "Path=%s\n", target_dir);
            fprintf(df, "Icon=%s/gui/icon.png\n", target_dir);
            fprintf(df, "Terminal=false\n");
            fprintf(df, "Categories=AudioVideo;Video;Graphics;\n");
            fprintf(df, "StartupNotify=true\n");
            fprintf(df, "StartupWMClass=CorridorKey Studio\n");
            fclose(df);
            chmod(desk_path, 0755);

            // mark trusted on desktop surface for gnome and kde
            if (i == 0) {
                char gio_cmd[1024];
                snprintf(gio_cmd, sizeof(gio_cmd), "gio set \"%s\" metadata::trusted true 2>/dev/null || true", desk_path);
                system(gio_cmd);
            }
        }
    }

    system("update-desktop-database ~/.local/share/applications 2>/dev/null || true");
    send_log("created desktop and application menu entries");
}

static gboolean is_build_installed(const char *target_dir) {
    if (!target_dir || strlen(target_dir) == 0) return FALSE;
    char launcher[1024];
    char pkg_dir[1024];
    snprintf(launcher, sizeof(launcher), "%s/launch_gui.sh", target_dir);
    snprintf(pkg_dir, sizeof(pkg_dir), "%s/corridorkey", target_dir);
    return (access(launcher, F_OK) == 0 && access(pkg_dir, F_OK) == 0);
}

static char *get_installed_commit(const char *target_dir) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/.build_version", target_dir);
    FILE *fp = fopen(path, "r");
    if (fp) {
        char line[256];
        while (fgets(line, sizeof(line), fp)) {
            char val[128];
            if (sscanf(line, "commit=%127s", val) == 1) {
                fclose(fp);
                return g_strdup(val);
            }
        }
        fclose(fp);
    }

    char git_cmd[1024];
    snprintf(git_cmd, sizeof(git_cmd), "git -C \"%s\" rev-parse HEAD 2>/dev/null", target_dir);
    fp = popen(git_cmd, "r");
    if (fp) {
        char line[256];
        if (fgets(line, sizeof(line), fp)) {
            pclose(fp);
            size_t len = strlen(line);
            if (len > 0 && line[len - 1] == '\n') line[len - 1] = '\0';
            if (strlen(line) >= 7) return g_strdup(line);
        } else {
            pclose(fp);
        }
    }
    return NULL;
}

static char *get_remote_branch_commit(const char *branch) {
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "timeout 3s git ls-remote https://github.com/Yancovert/CorridorKey-Studio.git refs/heads/%s 2>/dev/null", branch);
    FILE *fp = popen(cmd, "r");
    if (!fp) return NULL;
    char line[256];
    char *hash = NULL;
    if (fgets(line, sizeof(line), fp)) {
        char commit[64];
        if (sscanf(line, "%63s", commit) == 1 && strlen(commit) >= 7) {
            hash = g_strdup(commit);
        }
    }
    pclose(fp);
    return hash;
}

static BuildState check_build_state(const char *target_dir) {
    if (!is_build_installed(target_dir)) return BUILD_NOT_INSTALLED;

    char *installed_commit = get_installed_commit(target_dir);
    char *remote_commit = get_remote_branch_commit(BUNDLED_BRANCH);

    BuildState state = BUILD_UPDATE_AVAILABLE;
    if (remote_commit) {
        if (installed_commit && strncmp(installed_commit, remote_commit, 7) == 0) {
            state = BUILD_UP_TO_DATE;
        } else {
            state = BUILD_UPDATE_AVAILABLE;
        }
        g_free(remote_commit);
    } else {
        if (installed_commit && strncmp(installed_commit, BUNDLED_COMMIT, 7) == 0) {
            state = BUILD_UP_TO_DATE;
        } else {
            state = BUILD_UPDATE_AVAILABLE;
        }
    }

    if (installed_commit) g_free(installed_commit);
    return state;
}

static void write_build_version(const char *target_dir, const char *branch, const char *commit) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/.build_version", target_dir);
    FILE *fp = fopen(path, "w");
    if (fp) {
        fprintf(fp, "branch=%s\n", branch);
        fprintf(fp, "commit=%s\n", commit);
        fprintf(fp, "installed_at=%ld\n", (long)time(NULL));
        fclose(fp);
    }
}

typedef struct {
    char *target_dir;
    char *weights_dir;
    gboolean shortcut;
    gboolean weights;
    gboolean lowvram;
    gboolean is_existing_build;
} InstallParams;

static gpointer install_worker_thread(gpointer user_data) {
    InstallParams *params = (InstallParams *)user_data;

    if (params->is_existing_build) {
        send_progress(0.10, "Updating CorridorKey Studio files...");
        send_log("existing build detected: updating code and runtime files...");

        // if target is a git repo, pull from branch
        char git_dir[1024];
        snprintf(git_dir, sizeof(git_dir), "%s/.git", params->target_dir);
        if (access(git_dir, F_OK) == 0) {
            send_log("updating via git branch app-linux...");
            run_command_stream("git pull origin app-linux 2>&1", params->target_dir);
        }

        // extract payload files to update code
        char tmp_zip[] = "/tmp/corridorkey_payload_XXXXXX.zip";
        int fd = mkstemps(tmp_zip, 4);
        if (fd >= 0) {
            write(fd, payload_zip, payload_zip_len);
            close(fd);

            send_log("extracting updated payload into install directory...");
            char extract_cmd[2048];
            snprintf(extract_cmd, sizeof(extract_cmd), "python3 -m zipfile -e \"%s\" \"%s\" || unzip -q -o \"%s\" -d \"%s\"",
                     tmp_zip, params->target_dir, tmp_zip, params->target_dir);
            run_command_stream(extract_cmd, NULL);
            unlink(tmp_zip);
        }

        char chmod_cmd[1024];
        snprintf(chmod_cmd, sizeof(chmod_cmd), "chmod +x \"%s/launch_gui.sh\"", params->target_dir);
        system(chmod_cmd);

        // verify python environment
        char venv_py[1024];
        snprintf(venv_py, sizeof(venv_py), "%s/venv/bin/python", params->target_dir);
        if (access(venv_py, F_OK) != 0) {
            send_progress(0.35, "Creating virtual environment...");
            send_log("virtualenv missing: creating fresh environment...");
            char venv_cmd[1024];
            if (system("which uv > /dev/null 2>&1") == 0) {
                snprintf(venv_cmd, sizeof(venv_cmd), "uv venv \"%s/venv\"", params->target_dir);
            } else {
                snprintf(venv_cmd, sizeof(venv_cmd), "python3 -m venv \"%s/venv\"", params->target_dir);
            }
            run_command_stream(venv_cmd, params->target_dir);

            send_progress(0.50, "Installing PyTorch CUDA & dependencies...");
            send_log("installing pytorch with cuda 12.8 support...");
            char pip_torch[2048];
            if (system("which uv > /dev/null 2>&1") == 0) {
                snprintf(pip_torch, sizeof(pip_torch),
                         "uv pip install --link-mode=copy torch torchvision --index-url https://download.pytorch.org/whl/cu128 --python \"%s/venv/bin/python\"",
                         params->target_dir);
            } else {
                snprintf(pip_torch, sizeof(pip_torch),
                         "\"%s/venv/bin/pip\" install torch torchvision --index-url https://download.pytorch.org/whl/cu128",
                         params->target_dir);
            }
            run_command_stream(pip_torch, params->target_dir);
        }

        // fast dependency check
        send_progress(0.70, "Verifying Python dependencies...");
        send_log("verifying requirements and pyside6...");
        char pip_reqs[2048];
        if (system("which uv > /dev/null 2>&1") == 0) {
            snprintf(pip_reqs, sizeof(pip_reqs),
                     "uv pip install --link-mode=copy -r requirements.txt PySide6 --python \"%s/venv/bin/python\"",
                     params->target_dir);
        } else {
            snprintf(pip_reqs, sizeof(pip_reqs),
                     "\"%s/venv/bin/pip\" install -r requirements.txt PySide6",
                     params->target_dir);
        }
        run_command_stream(pip_reqs, params->target_dir);

        // check weights - do not re-download if present
        char main_weights[1024];
        snprintf(main_weights, sizeof(main_weights), "%s/corridorkey_v2.safetensors", params->weights_dir);
        struct stat st_w;
        if (stat(main_weights, &st_w) == 0 && st_w.st_size > 1000000000LL) {
            send_progress(0.85, "Preserving existing weights...");
            send_log("existing foundation model weights (~5 GB) verified, skipping download");
        } else if (params->weights) {
            send_progress(0.80, "Downloading foundation models...");
            send_log("downloading foundation models (~5 GB)...");
            char dl_cmd[1024];
            snprintf(dl_cmd, sizeof(dl_cmd), "\"%s/venv/bin/python\" scripts/download_weights.py", params->target_dir);
            run_command_stream(dl_cmd, params->target_dir);
        }

        // refresh desktop entry
        if (params->shortcut) {
            send_progress(0.95, "Refreshing desktop entries...");
            create_desktop_shortcuts(params->target_dir);
        }

        write_build_version(params->target_dir, BUNDLED_BRANCH, BUNDLED_COMMIT);

        send_progress(1.0, "Update Complete!");
        send_log("update complete: core files, dependencies, and desktop entries refreshed");
        g_idle_add(on_idle_finished, GINT_TO_POINTER(1));

    } else {
        // clean installation
        send_progress(0.05, "Extracting application files...");
        send_log("preparing target directory...");

        char mkdir_cmd[1024];
        snprintf(mkdir_cmd, sizeof(mkdir_cmd), "mkdir -p \"%s\" \"%s\"", params->target_dir, params->weights_dir);
        system(mkdir_cmd);

        char tmp_zip[] = "/tmp/corridorkey_payload_XXXXXX.zip";
        int fd = mkstemps(tmp_zip, 4);
        if (fd >= 0) {
            write(fd, payload_zip, payload_zip_len);
            close(fd);

            send_log("extracting embedded files into install location...");
            char extract_cmd[2048];
            snprintf(extract_cmd, sizeof(extract_cmd), "python3 -m zipfile -e \"%s\" \"%s\" || unzip -q -o \"%s\" -d \"%s\"",
                     tmp_zip, params->target_dir, tmp_zip, params->target_dir);
            run_command_stream(extract_cmd, NULL);
            unlink(tmp_zip);
        }

        char chmod_cmd[1024];
        snprintf(chmod_cmd, sizeof(chmod_cmd), "chmod +x \"%s/launch_gui.sh\"", params->target_dir);
        system(chmod_cmd);

        send_progress(0.20, "Setting up virtual environment...");
        send_log("creating virtual environment...");

        char venv_cmd[1024];
        if (system("which uv > /dev/null 2>&1") == 0) {
            snprintf(venv_cmd, sizeof(venv_cmd), "uv venv \"%s/venv\"", params->target_dir);
        } else {
            snprintf(venv_cmd, sizeof(venv_cmd), "python3 -m venv \"%s/venv\"", params->target_dir);
        }
        run_command_stream(venv_cmd, params->target_dir);

        send_progress(0.45, "Installing PyTorch CUDA & dependencies...");
        send_log("installing pytorch with cuda 12.8 support...");

        char pip_torch[2048];
        char pip_reqs[2048];
        if (system("which uv > /dev/null 2>&1") == 0) {
            snprintf(pip_torch, sizeof(pip_torch),
                     "uv pip install --link-mode=copy torch torchvision --index-url https://download.pytorch.org/whl/cu128 --python \"%s/venv/bin/python\"",
                     params->target_dir);
            snprintf(pip_reqs, sizeof(pip_reqs),
                     "uv pip install --link-mode=copy -r requirements.txt PySide6 --python \"%s/venv/bin/python\"",
                     params->target_dir);
        } else {
            snprintf(pip_torch, sizeof(pip_torch),
                     "\"%s/venv/bin/pip\" install torch torchvision --index-url https://download.pytorch.org/whl/cu128",
                     params->target_dir);
            snprintf(pip_reqs, sizeof(pip_reqs),
                     "\"%s/venv/bin/pip\" install -r requirements.txt PySide6",
                     params->target_dir);
        }

        run_command_stream(pip_torch, params->target_dir);
        send_log("installing requirements and pyside6...");
        run_command_stream(pip_reqs, params->target_dir);

        if (params->weights) {
            send_progress(0.75, "Checking foundation models...");
            send_log("downloading/verifying foundation models (~5 GB)...");
            char dl_cmd[1024];
            snprintf(dl_cmd, sizeof(dl_cmd), "\"%s/venv/bin/python\" scripts/download_weights.py", params->target_dir);
            run_command_stream(dl_cmd, params->target_dir);
        }

        if (params->shortcut) {
            send_progress(0.90, "Creating desktop launcher...");
            create_desktop_shortcuts(params->target_dir);
        }

        write_build_version(params->target_dir, BUNDLED_BRANCH, BUNDLED_COMMIT);

        send_progress(1.0, "Installation Complete!");
        g_idle_add(on_idle_finished, GINT_TO_POINTER(1));
    }

    g_free(params->target_dir);
    g_free(params->weights_dir);
    g_free(params);
    return NULL;
}

static double get_path_free_gb(const char *path) {
    char test_path[1024];
    strncpy(test_path, path, sizeof(test_path) - 1);
    test_path[sizeof(test_path) - 1] = '\0';

    while (strlen(test_path) > 1 && access(test_path, F_OK) != 0) {
        char *slash = strrchr(test_path, '/');
        if (!slash || slash == test_path) {
            strcpy(test_path, "/");
            break;
        }
        *slash = '\0';
    }

    struct statvfs st;
    if (statvfs(test_path, &st) == 0) {
        unsigned long long free_bytes = (unsigned long long)st.f_bavail * st.f_frsize;
        return (double)free_bytes / (1024.0 * 1024.0 * 1024.0);
    }
    return 0.0;
}

static void update_space_label(void) {
    if (!g_app || !g_app->entry_install || !g_app->lbl_space) return;
    const char *path = gtk_entry_get_text(GTK_ENTRY(g_app->entry_install));
    double gb = get_path_free_gb(path);
    char buf[256];
    if (gb >= 10.0) {
        snprintf(buf, sizeof(buf), "<span foreground='#3dd68c' size='small'><b>%.1f GB available</b> on target partition (~5 GB required)</span>", gb);
    } else {
        snprintf(buf, sizeof(buf), "<span foreground='#ffaa00' size='small'><b>%.1f GB available</b> (warning: low disk space, ~5 GB required)</span>", gb);
    }
    gtk_label_set_markup(GTK_LABEL(g_app->lbl_space), buf);
}

static void update_build_detection_ui(void) {
    if (!g_app || !g_app->entry_install || !g_app->btn_install || !g_app->lbl_status) return;

    const char *target_dir = gtk_entry_get_text(GTK_ENTRY(g_app->entry_install));
    if (!target_dir || strlen(target_dir) == 0) return;

    if (!is_build_installed(target_dir)) {
        g_app->is_existing_build = FALSE;
        gtk_button_set_label(GTK_BUTTON(g_app->btn_install), "Install CorridorKey Studio");
        gtk_label_set_text(GTK_LABEL(g_app->lbl_status), "Ready to install.");
        gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(g_app->chk_weights), TRUE);
        return;
    }

    g_app->is_existing_build = TRUE;

    // auto uncheck weights if model file already exists in weights dir
    const char *wgt_dir = gtk_entry_get_text(GTK_ENTRY(g_app->entry_weights));
    char main_weights[1024];
    snprintf(main_weights, sizeof(main_weights), "%s/corridorkey_v2.safetensors", wgt_dir);
    struct stat st_w;
    if (stat(main_weights, &st_w) == 0 && st_w.st_size > 1000000000LL) {
        gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(g_app->chk_weights), FALSE);
    }

    BuildState state = check_build_state(target_dir);
    if (state == BUILD_UPDATE_AVAILABLE) {
        gtk_button_set_label(GTK_BUTTON(g_app->btn_install), "Update CorridorKey Studio");
        gtk_label_set_markup(GTK_LABEL(g_app->lbl_status),
            "<span foreground='#3dd68c' weight='bold'>Existing build detected. Update available from branch app-linux.</span>");
    } else {
        gtk_button_set_label(GTK_BUTTON(g_app->btn_install), "Update / Repair Installation");
        gtk_label_set_markup(GTK_LABEL(g_app->lbl_status),
            "<span foreground='#58a6ff' weight='bold'>Existing build detected (up to date on branch app-linux).</span>");
    }
}

static void on_install_path_changed(GtkEditable *editable, gpointer user_data) {
    update_space_label();
    update_build_detection_ui();
}

static void on_browse_install(GtkButton *btn, gpointer user_data) {
    GtkWidget *dialog = gtk_file_chooser_dialog_new("Select Install Directory",
                                                   GTK_WINDOW(g_app->window),
                                                   GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                                   "Cancel", GTK_RESPONSE_CANCEL,
                                                   "Select", GTK_RESPONSE_ACCEPT,
                                                   NULL);
    if (gtk_dialog_run(GTK_DIALOG(dialog)) == GTK_RESPONSE_ACCEPT) {
        char *folder = gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(dialog));
        gtk_entry_set_text(GTK_ENTRY(g_app->entry_install), folder);

        char wgt_sub[1024];
        snprintf(wgt_sub, sizeof(wgt_sub), "%s/weights", folder);
        gtk_entry_set_text(GTK_ENTRY(g_app->entry_weights), wgt_sub);

        g_free(folder);
        update_build_detection_ui();
    }
    gtk_widget_destroy(dialog);
}

static void on_browse_weights(GtkButton *btn, gpointer user_data) {
    GtkWidget *dialog = gtk_file_chooser_dialog_new("Select Weights Directory",
                                                   GTK_WINDOW(g_app->window),
                                                   GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                                   "Cancel", GTK_RESPONSE_CANCEL,
                                                   "Select", GTK_RESPONSE_ACCEPT,
                                                   NULL);
    if (gtk_dialog_run(GTK_DIALOG(dialog)) == GTK_RESPONSE_ACCEPT) {
        char *folder = gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(dialog));
        gtk_entry_set_text(GTK_ENTRY(g_app->entry_weights), folder);
        g_free(folder);
        update_build_detection_ui();
    }
    gtk_widget_destroy(dialog);
}

static void on_install_clicked(GtkButton *btn, gpointer user_data) {
    if (g_app->installed) {
        const char *inst = gtk_entry_get_text(GTK_ENTRY(g_app->entry_install));
        char launch_cmd[1024];
        snprintf(launch_cmd, sizeof(launch_cmd), "\"%s/launch_gui.sh\" &", inst);
        system(launch_cmd);
        gtk_widget_destroy(g_app->window);
        return;
    }

    gtk_widget_set_sensitive(g_app->btn_install, FALSE);

    InstallParams *params = g_new0(InstallParams, 1);
    params->target_dir = g_strdup(gtk_entry_get_text(GTK_ENTRY(g_app->entry_install)));
    params->weights_dir = g_strdup(gtk_entry_get_text(GTK_ENTRY(g_app->entry_weights)));
    params->shortcut = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(g_app->chk_shortcut));
    params->weights = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(g_app->chk_weights));
    params->lowvram = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(g_app->chk_lowvram));
    params->is_existing_build = g_app->is_existing_build;

    g_thread_new("installer_thread", install_worker_thread, params);
}

static void find_best_drive(char *out_best, size_t max_len, double *out_free_gb) {
    const char *home = getenv("HOME");
    if (!home) home = "/tmp";

    strncpy(out_best, home, max_len - 1);
    out_best[max_len - 1] = '\0';
    double max_free = get_path_free_gb(home);

    FILE *fp = setmntent("/proc/mounts", "r");
    if (fp) {
        struct mntent *ent;
        while ((ent = getmntent(fp)) != NULL) {
            if (strncmp(ent->mnt_fsname, "/dev/", 5) == 0 &&
                strncmp(ent->mnt_dir, "/boot", 5) != 0) {
                char test_user_dir[1024];
                const char *user = getenv("USER");
                const char *candidate = NULL;

                if (access(ent->mnt_dir, W_OK) == 0) {
                    candidate = ent->mnt_dir;
                } else if (user) {
                    snprintf(test_user_dir, sizeof(test_user_dir), "%s/%s", ent->mnt_dir, user);
                    if (access(test_user_dir, W_OK) == 0) {
                        candidate = test_user_dir;
                    }
                }

                if (candidate) {
                    double free_gb = get_path_free_gb(candidate);
                    if (free_gb > max_free) {
                        max_free = free_gb;
                        strncpy(out_best, candidate, max_len - 1);
                        out_best[max_len - 1] = '\0';
                    }
                }
            }
        }
        endmntent(fp);
    }

    if (out_free_gb) *out_free_gb = max_free;
}

static char *detect_gpu_str(void) {
    FILE *fp = popen("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null", "r");
    if (!fp) return g_strdup("Linux x86_64 | Generic / CPU");
    char line[256];
    if (fgets(line, sizeof(line), fp)) {
        pclose(fp);
        size_t len = strlen(line);
        if (len > 0 && line[len - 1] == '\n') line[len - 1] = '\0';
        return g_strdup_printf("Linux x86_64 | GPU: %s", line);
    }
    pclose(fp);
    return g_strdup("Linux x86_64 | NVIDIA GPU auto-detect");
}

int main(int argc, char *argv[]) {
    gtk_init(&argc, &argv);

    g_app = g_new0(AppWidgets, 1);

    g_app->window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(g_app->window), "CorridorKey Studio Setup");
    gtk_window_set_default_size(GTK_WINDOW(g_app->window), 580, 530);
    gtk_window_set_position(GTK_WINDOW(g_app->window), GTK_WIN_POS_CENTER);
    g_signal_connect(g_app->window, "destroy", G_CALLBACK(gtk_main_quit), NULL);

    GtkWidget *main_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 10);
    gtk_container_set_border_width(GTK_CONTAINER(main_box), 16);
    gtk_container_add(GTK_CONTAINER(g_app->window), main_box);

    // header
    GtkWidget *lbl_title = gtk_label_new(NULL);
    gtk_label_set_markup(GTK_LABEL(lbl_title), "<span size='large' weight='bold'>CorridorKey Studio Installer</span>");
    gtk_widget_set_halign(lbl_title, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(main_box), lbl_title, FALSE, FALSE, 0);

    char *gpu_desc = detect_gpu_str();
    GtkWidget *lbl_gpu = gtk_label_new(gpu_desc);
    g_free(gpu_desc);
    gtk_widget_set_halign(lbl_gpu, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(main_box), lbl_gpu, FALSE, FALSE, 0);

    // frame 1: directories
    GtkWidget *frame_dir = gtk_frame_new("Target Directories");
    GtkWidget *box_dir = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_container_set_border_width(GTK_CONTAINER(box_dir), 10);
    gtk_container_add(GTK_CONTAINER(frame_dir), box_dir);
    gtk_box_pack_start(GTK_BOX(main_box), frame_dir, FALSE, FALSE, 0);

    char best_drive[512];
    double best_free_gb = 0.0;
    find_best_drive(best_drive, sizeof(best_drive), &best_free_gb);

    char def_inst[512];
    char def_wgt[512];
    snprintf(def_inst, sizeof(def_inst), "%s/CorridorKey-Studio", best_drive);
    snprintf(def_wgt, sizeof(def_wgt), "%s/CorridorKey-Studio/weights", best_drive);

    GtkWidget *lbl_rec = gtk_label_new(NULL);
    char rec_str[512];
    snprintf(rec_str, sizeof(rec_str), "<span foreground='#8b949e' size='small'>Recommended drive with most space: <b>%s</b> (<b>%.1f GB free</b>)</span>", best_drive, best_free_gb);
    gtk_label_set_markup(GTK_LABEL(lbl_rec), rec_str);
    gtk_widget_set_halign(lbl_rec, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(box_dir), lbl_rec, FALSE, FALSE, 0);

    GtkWidget *lbl_inst = gtk_label_new("Installation Directory:");
    gtk_widget_set_halign(lbl_inst, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(box_dir), lbl_inst, FALSE, FALSE, 0);

    GtkWidget *row_inst = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    g_app->entry_install = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(g_app->entry_install), def_inst);
    g_signal_connect(g_app->entry_install, "changed", G_CALLBACK(on_install_path_changed), NULL);
    gtk_box_pack_start(GTK_BOX(row_inst), g_app->entry_install, TRUE, TRUE, 0);
    GtkWidget *btn_browse1 = gtk_button_new_with_label("Browse...");
    g_signal_connect(btn_browse1, "clicked", G_CALLBACK(on_browse_install), NULL);
    gtk_box_pack_start(GTK_BOX(row_inst), btn_browse1, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box_dir), row_inst, FALSE, FALSE, 0);

    g_app->lbl_space = gtk_label_new(NULL);
    gtk_widget_set_halign(g_app->lbl_space, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(box_dir), g_app->lbl_space, FALSE, FALSE, 0);

    GtkWidget *lbl_wgt = gtk_label_new("Weights & Cache Directory:");
    gtk_widget_set_halign(lbl_wgt, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(box_dir), lbl_wgt, FALSE, FALSE, 0);

    GtkWidget *row_wgt = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    g_app->entry_weights = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(g_app->entry_weights), def_wgt);
    gtk_box_pack_start(GTK_BOX(row_wgt), g_app->entry_weights, TRUE, TRUE, 0);
    GtkWidget *btn_browse2 = gtk_button_new_with_label("Browse...");
    g_signal_connect(btn_browse2, "clicked", G_CALLBACK(on_browse_weights), NULL);
    gtk_box_pack_start(GTK_BOX(row_wgt), btn_browse2, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box_dir), row_wgt, FALSE, FALSE, 0);

    // frame 2: options
    GtkWidget *frame_opt = gtk_frame_new("Preferences");
    GtkWidget *box_opt = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_container_set_border_width(GTK_CONTAINER(box_opt), 10);
    gtk_container_add(GTK_CONTAINER(frame_opt), box_opt);
    gtk_box_pack_start(GTK_BOX(main_box), frame_opt, FALSE, FALSE, 0);

    g_app->chk_shortcut = gtk_check_button_new_with_label("Create Desktop & Application Menu Shortcut");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(g_app->chk_shortcut), TRUE);
    gtk_box_pack_start(GTK_BOX(box_opt), g_app->chk_shortcut, FALSE, FALSE, 0);

    g_app->chk_weights = gtk_check_button_new_with_label("Pre-download ~5 GB foundation models immediately");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(g_app->chk_weights), TRUE);
    gtk_box_pack_start(GTK_BOX(box_opt), g_app->chk_weights, FALSE, FALSE, 0);

    g_app->chk_lowvram = gtk_check_button_new_with_label("Auto-detect GPU and configure performance profile");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(g_app->chk_lowvram), TRUE);
    gtk_box_pack_start(GTK_BOX(box_opt), g_app->chk_lowvram, FALSE, FALSE, 0);

    // status & progress
    g_app->lbl_status = gtk_label_new("Ready to install.");
    gtk_widget_set_halign(g_app->lbl_status, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(main_box), g_app->lbl_status, FALSE, FALSE, 0);

    g_app->progress_bar = gtk_progress_bar_new();
    gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(g_app->progress_bar), 0.0);
    gtk_box_pack_start(GTK_BOX(main_box), g_app->progress_bar, FALSE, FALSE, 0);

    // log box
    GtkWidget *scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_shadow_type(GTK_SCROLLED_WINDOW(scroll), GTK_SHADOW_IN);
    gtk_widget_set_size_request(scroll, -1, 95);
    g_app->text_log = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(g_app->text_log), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(g_app->text_log), FALSE);
    gtk_container_add(GTK_CONTAINER(scroll), g_app->text_log);
    gtk_box_pack_start(GTK_BOX(main_box), scroll, TRUE, TRUE, 0);

    // buttons
    GtkWidget *btn_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_widget_set_halign(btn_box, GTK_ALIGN_END);

    g_app->btn_cancel = gtk_button_new_with_label("Exit");
    g_signal_connect_swapped(g_app->btn_cancel, "clicked", G_CALLBACK(gtk_widget_destroy), g_app->window);
    gtk_box_pack_start(GTK_BOX(btn_box), g_app->btn_cancel, FALSE, FALSE, 0);

    g_app->btn_install = gtk_button_new_with_label("Install CorridorKey Studio");
    g_signal_connect(g_app->btn_install, "clicked", G_CALLBACK(on_install_clicked), NULL);
    gtk_box_pack_start(GTK_BOX(btn_box), g_app->btn_install, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(main_box), btn_box, FALSE, FALSE, 0);

    update_space_label();
    update_build_detection_ui();

    gtk_widget_show_all(g_app->window);
    gtk_main();

    return 0;
}
