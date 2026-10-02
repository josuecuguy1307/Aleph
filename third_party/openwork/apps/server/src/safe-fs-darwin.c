#define _DARWIN_C_SOURCE 1
#include <node_api.h>
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* macOS-only Node-API boundary. Every component is opened relative to an
 * already-open directory, with O_NOFOLLOW. No checked pathname is used later. */
static void fail(napi_env env, const char *message) {
    napi_throw_error(env, "ALEPH_SAFE_FS", message);
}

static int string_arg(napi_env env, napi_value value, char *dst, size_t cap) {
    size_t length = 0;
    if (napi_get_value_string_utf8(env, value, dst, cap, &length) != napi_ok ||
        length == 0 || length >= cap - 1 || strlen(dst) != length) {
        fail(env, "invalid filesystem path");
        return -1;
    }
    return 0;
}

static int directory(int fd, const char *component, int create) {
    int next = openat(fd, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (next < 0 && errno == ENOENT && create) {
        if (mkdirat(fd, component, 0700) != 0 && errno != EEXIST) return -1;
        next = openat(fd, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    }
    return next;
}

static int root_fd(const char *root) {
    if (root[0] != '/' || root[1] == 0) { errno = EINVAL; return -1; }
    int fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return -1;
    char path[PATH_MAX];
    if (strlen(root) >= sizeof(path)) { close(fd); errno = ENAMETOOLONG; return -1; }
    strcpy(path, root + 1);
    char *save = NULL;
    for (char *part = strtok_r(path, "/", &save); part; part = strtok_r(NULL, "/", &save)) {
        if (!strcmp(part, ".") || !strcmp(part, "..")) { close(fd); errno = EINVAL; return -1; }
        int next = directory(fd, part, 0);
        close(fd);
        if (next < 0) return -1;
        fd = next;
    }
    return fd;
}

static int parent_fd(const char *root, const char *relative, int create, char *leaf) {
    if (!relative[0] || relative[0] == '/' || relative[strlen(relative) - 1] == '/') {
        errno = EINVAL; return -1;
    }
    int fd = root_fd(root);
    if (fd < 0) return -1;
    char path[PATH_MAX];
    strcpy(path, relative);
    char *save = NULL;
    char *part = strtok_r(path, "/", &save);
    while (part) {
        if (!strcmp(part, ".") || !strcmp(part, "..") || strlen(part) > NAME_MAX) {
            close(fd); errno = EINVAL; return -1;
        }
        char *next = strtok_r(NULL, "/", &save);
        if (!next) { strcpy(leaf, part); return fd; }
        int child = directory(fd, part, create);
        close(fd);
        if (child < 0) return -1;
        fd = child;
        part = next;
    }
    close(fd); errno = EINVAL; return -1;
}

static int path_args(napi_env env, napi_callback_info info, size_t wanted,
                     napi_value *argv, char *root, char *rel) {
    size_t argc = wanted;
    if (napi_get_cb_info(env, info, &argc, argv, NULL, NULL) != napi_ok || argc != wanted) {
        fail(env, "invalid filesystem call arity"); return -1;
    }
    if (string_arg(env, argv[0], root, PATH_MAX) || string_arg(env, argv[1], rel, PATH_MAX)) return -1;
    return 0;
}

static napi_value fd_value(napi_env env, int fd) {
    napi_value result;
    napi_create_int32(env, fd, &result);
    return result;
}

static napi_value open_file(napi_env env, napi_callback_info info) {
    napi_value args[2]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 2, args, root, rel)) return NULL;
    int parent = parent_fd(root, rel, 0, leaf);
    if (parent < 0) { fail(env, "unsafe or missing directory"); return NULL; }
    int fd = openat(parent, leaf, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    close(parent);
    struct stat st;
    if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        if (fd >= 0) close(fd);
        fail(env, "unsafe or missing regular file"); return NULL;
    }
    return fd_value(env, fd);
}

static napi_value path_kind(napi_env env, napi_callback_info info) {
    napi_value args[2], result; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 2, args, root, rel)) return NULL;
    int parent = parent_fd(root, rel, 0, leaf);
    if (parent < 0) { fail(env, "unsafe or missing directory"); return NULL; }
    struct stat st;
    int rc = fstatat(parent, leaf, &st, AT_SYMLINK_NOFOLLOW);
    int saved_errno = errno;
    close(parent);
    const char *kind;
    if (rc < 0 && saved_errno == ENOENT) kind = "missing";
    else if (rc < 0) { fail(env, "unsafe file metadata"); return NULL; }
    else if (S_ISREG(st.st_mode)) kind = "regular";
    else if (S_ISDIR(st.st_mode)) kind = "directory";
    else if (S_ISLNK(st.st_mode)) kind = "symlink";
    else kind = "other";
    napi_create_string_utf8(env, kind, NAPI_AUTO_LENGTH, &result);
    return result;
}

static napi_value open_directory(napi_env env, napi_callback_info info) {
    napi_value args[2]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 2, args, root, rel)) return NULL;
    if (!strcmp(rel, ".")) {
        int root_handle = root_fd(root);
        if (root_handle < 0) { fail(env, "unsafe workspace root"); return NULL; }
        return fd_value(env, root_handle);
    }
    int parent = parent_fd(root, rel, 0, leaf);
    if (parent < 0) { fail(env, "unsafe or missing directory"); return NULL; }
    int fd = directory(parent, leaf, 0);
    close(parent);
    if (fd < 0) { fail(env, "unsafe or missing directory"); return NULL; }
    return fd_value(env, fd);
}

static napi_value list_directory(napi_env env, napi_callback_info info) {
    napi_value args[2]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 2, args, root, rel)) return NULL;
    int fd;
    if (!strcmp(rel, ".")) fd = root_fd(root);
    else {
        int parent = parent_fd(root, rel, 0, leaf);
        if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
        fd = directory(parent, leaf, 0);
        close(parent);
    }
    if (fd < 0) { fail(env, "unsafe directory"); return NULL; }
    DIR *stream = fdopendir(fd);
    if (!stream) { close(fd); fail(env, "directory listing unavailable"); return NULL; }
    napi_value result; napi_create_array(env, &result);
    unsigned index = 0;
    struct dirent *entry;
    while ((entry = readdir(stream))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        struct stat st;
        if (fstatat(fd, entry->d_name, &st, AT_SYMLINK_NOFOLLOW) != 0 ||
            (!S_ISREG(st.st_mode) && !S_ISDIR(st.st_mode))) continue;
        napi_value item, name, directory_value;
        napi_create_object(env, &item);
        napi_create_string_utf8(env, entry->d_name, NAPI_AUTO_LENGTH, &name);
        napi_get_boolean(env, S_ISDIR(st.st_mode), &directory_value);
        napi_set_named_property(env, item, "name", name);
        napi_set_named_property(env, item, "directory", directory_value);
        napi_set_element(env, result, index++, item);
    }
    closedir(stream);
    return result;
}

static napi_value make_directory(napi_env env, napi_callback_info info) {
    napi_value args[2]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 2, args, root, rel)) return NULL;
    int parent = parent_fd(root, rel, 1, leaf);
    if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
    int fd = directory(parent, leaf, 1);
    close(parent);
    if (fd < 0) { fail(env, "unsafe directory target"); return NULL; }
    close(fd);
    napi_value result; napi_get_undefined(env, &result); return result;
}

static napi_value write_file(napi_env env, napi_callback_info info) {
    napi_value args[3]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 3, args, root, rel)) return NULL;
    void *bytes = NULL; size_t size = 0;
    if (napi_get_buffer_info(env, args[2], &bytes, &size) != napi_ok || size > 250000000) {
        fail(env, "invalid write buffer"); return NULL;
    }
    int parent = parent_fd(root, rel, 1, leaf);
    if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
    struct stat destination;
    if (fstatat(parent, leaf, &destination, AT_SYMLINK_NOFOLLOW) == 0) {
        if (!S_ISREG(destination.st_mode) || !(destination.st_mode & S_IWUSR)) {
            close(parent); fail(env, "unsafe destination"); return NULL;
        }
    } else if (errno != ENOENT) {
        close(parent); fail(env, "unavailable destination"); return NULL;
    }
    char tmp[NAME_MAX + 1];
    unsigned char random[16];
    int random_fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (random_fd < 0 || read(random_fd, random, sizeof(random)) != sizeof(random)) {
        if (random_fd >= 0) close(random_fd);
        close(parent); fail(env, "temporary name unavailable"); return NULL;
    }
    close(random_fd);
    static const char hex[] = "0123456789abcdef";
    strcpy(tmp, ".aleph-tmp-");
    for (int i = 0; i < 16; i++) { tmp[11 + i*2] = hex[random[i] >> 4]; tmp[12 + i*2] = hex[random[i] & 15]; }
    tmp[43] = 0;
    int fd = openat(parent, tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) { close(parent); fail(env, "temporary file unavailable"); return NULL; }
    int ok = 1; size_t offset = 0;
    while (offset < size) {
        ssize_t n = write(fd, (char *)bytes + offset, size - offset);
        if (n <= 0) { ok = 0; break; }
        offset += (size_t)n;
    }
    if (ok && fsync(fd) != 0) ok = 0;
    struct stat target;
    if (ok && fstatat(parent, leaf, &target, AT_SYMLINK_NOFOLLOW) == 0 && !S_ISREG(target.st_mode)) ok = 0;
    if (ok && renameat(parent, tmp, parent, leaf) != 0) ok = 0;
    struct stat written;
    if (ok && fstat(fd, &written) != 0) ok = 0;
    close(fd);
    if (!ok) unlinkat(parent, tmp, 0);
    close(parent);
    if (!ok) { fail(env, "atomic file write rejected"); return NULL; }
    napi_value result; napi_create_double(env, (double)written.st_mtimespec.tv_sec * 1000.0 +
                                     (double)written.st_mtimespec.tv_nsec / 1000000.0, &result);
    return result;
}

static napi_value create_file(napi_env env, napi_callback_info info) {
    napi_value args[3]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 3, args, root, rel)) return NULL;
    void *bytes = NULL; size_t size = 0;
    if (napi_get_buffer_info(env, args[2], &bytes, &size) != napi_ok || size > 250000000) {
        fail(env, "invalid create buffer"); return NULL;
    }
    int parent = parent_fd(root, rel, 1, leaf);
    if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
    int fd = openat(parent, leaf, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    close(parent);
    if (fd < 0) { fail(env, "file already exists or unsafe"); return NULL; }
    int ok = 1; size_t offset = 0;
    while (offset < size) {
        ssize_t n = write(fd, (char *)bytes + offset, size - offset);
        if (n <= 0) { ok = 0; break; }
        offset += (size_t)n;
    }
    if (ok && fsync(fd) != 0) ok = 0;
    close(fd);
    if (!ok) { fail(env, "file create failed"); return NULL; }
    napi_value result; napi_get_undefined(env, &result); return result;
}

static napi_value append_file(napi_env env, napi_callback_info info) {
    napi_value args[3]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 3, args, root, rel)) return NULL;
    void *bytes = NULL; size_t size = 0;
    if (napi_get_buffer_info(env, args[2], &bytes, &size) != napi_ok || size > 65536) {
        fail(env, "invalid append buffer"); return NULL;
    }
    int parent = parent_fd(root, rel, 1, leaf);
    if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
    int fd = openat(parent, leaf, O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    close(parent);
    struct stat st;
    if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        if (fd >= 0) close(fd);
        fail(env, "unsafe append target"); return NULL;
    }
    size_t offset = 0;
    while (offset < size) {
        ssize_t n = write(fd, (char *)bytes + offset, size - offset);
        if (n <= 0) break;
        offset += (size_t)n;
    }
    int ok = offset == size && fsync(fd) == 0;
    close(fd);
    if (!ok) { fail(env, "append failed"); return NULL; }
    napi_value result; napi_get_undefined(env, &result); return result;
}

static napi_value move_file(napi_env env, napi_callback_info info) {
    napi_value args[3]; char root[PATH_MAX], from[PATH_MAX], to[PATH_MAX];
    size_t argc = 3;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 3 ||
        string_arg(env, args[0], root, PATH_MAX) || string_arg(env, args[1], from, PATH_MAX) ||
        string_arg(env, args[2], to, PATH_MAX)) return NULL;
    char a[NAME_MAX + 1], b[NAME_MAX + 1];
    int src = parent_fd(root, from, 0, a);
    if (src < 0) { fail(env, "unsafe source ancestor"); return NULL; }
    int dst = parent_fd(root, to, 1, b);
    if (dst < 0) { close(src); fail(env, "unsafe destination ancestor"); return NULL; }
    struct stat st;
    int ok = fstatat(src, a, &st, AT_SYMLINK_NOFOLLOW) == 0 && !S_ISLNK(st.st_mode) &&
             renameat(src, a, dst, b) == 0;
    close(src); close(dst);
    if (!ok) { fail(env, "unsafe rename rejected"); return NULL; }
    napi_value result; napi_get_undefined(env, &result); return result;
}

static int remove_tree(int parent, const char *name, int depth, unsigned *remaining) {
    if (depth > 32 || !*remaining) { errno = E2BIG; return -1; }
    (*remaining)--;
    int fd = directory(parent, name, 0);
    if (fd < 0) return -1;
    DIR *stream = fdopendir(fd);
    if (!stream) { close(fd); return -1; }
    int ok = 0;
    struct dirent *entry;
    while ((entry = readdir(stream))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        struct stat st;
        if (fstatat(fd, entry->d_name, &st, AT_SYMLINK_NOFOLLOW) != 0) { ok = -1; break; }
        if (S_ISDIR(st.st_mode)) {
            if (remove_tree(fd, entry->d_name, depth + 1, remaining) != 0) { ok = -1; break; }
        } else if (S_ISREG(st.st_mode)) {
            if (!*remaining || unlinkat(fd, entry->d_name, 0) != 0) { ok = -1; break; }
            (*remaining)--;
        } else { ok = -1; break; }
    }
    closedir(stream);
    if (ok == 0) ok = unlinkat(parent, name, AT_REMOVEDIR);
    return ok;
}

static napi_value remove_file(napi_env env, napi_callback_info info) {
    napi_value args[3]; char root[PATH_MAX], rel[PATH_MAX], leaf[NAME_MAX + 1];
    if (path_args(env, info, 3, args, root, rel)) return NULL;
    bool recursive = false;
    if (napi_get_value_bool(env, args[2], &recursive) != napi_ok) {
        fail(env, "invalid recursive option"); return NULL;
    }
    int parent = parent_fd(root, rel, 0, leaf);
    if (parent < 0) { fail(env, "unsafe directory ancestor"); return NULL; }
    struct stat st;
    int ok = fstatat(parent, leaf, &st, AT_SYMLINK_NOFOLLOW) == 0 &&
             (S_ISREG(st.st_mode) || S_ISDIR(st.st_mode));
    if (ok) {
        if (S_ISDIR(st.st_mode) && recursive) {
            unsigned remaining = 10000;
            ok = remove_tree(parent, leaf, 0, &remaining) == 0;
        } else ok = unlinkat(parent, leaf, S_ISDIR(st.st_mode) ? AT_REMOVEDIR : 0) == 0;
    }
    close(parent);
    if (!ok) { fail(env, "unsafe delete rejected"); return NULL; }
    napi_value result; napi_get_undefined(env, &result); return result;
}

static napi_value init(napi_env env, napi_value exports) {
    napi_property_descriptor methods[] = {
        {"openFile", NULL, open_file, NULL, NULL, NULL, napi_default, NULL},
        {"pathKind", NULL, path_kind, NULL, NULL, NULL, napi_default, NULL},
        {"openDirectory", NULL, open_directory, NULL, NULL, NULL, napi_default, NULL},
        {"list", NULL, list_directory, NULL, NULL, NULL, napi_default, NULL},
        {"mkdir", NULL, make_directory, NULL, NULL, NULL, napi_default, NULL},
        {"writeFile", NULL, write_file, NULL, NULL, NULL, napi_default, NULL},
        {"createFile", NULL, create_file, NULL, NULL, NULL, napi_default, NULL},
        {"appendFile", NULL, append_file, NULL, NULL, NULL, napi_default, NULL},
        {"rename", NULL, move_file, NULL, NULL, NULL, napi_default, NULL},
        {"remove", NULL, remove_file, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(methods)/sizeof(methods[0]), methods);
    return exports;
}
NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
