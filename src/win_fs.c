#ifndef _WIN32
#error "win_fs.c is only for Windows targets"
#endif

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#include <windows.h>
#include <winternl.h>
#include <bcrypt.h>
#include <io.h>
#include <fcntl.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "win_fs.h"

#ifndef S_IFLNK
#define S_IFLNK 0120000
#endif

struct cat_win_dir {
    HANDLE handle;
    int fd;
    unsigned char buffer[65536];
    size_t offset, valid;
    int first, finished;
    struct dirent entry;
};

static int map_win_error(DWORD error);

static int private_security(SECURITY_ATTRIBUTES *attributes, PSECURITY_DESCRIPTOR *descriptor,
                           PACL *acl, PTOKEN_USER *token_user) {
    HANDLE token = NULL;
    DWORD required = 0;
    BYTE system_sid[SECURITY_MAX_SID_SIZE];
    DWORD system_sid_size = sizeof(system_sid);
    *descriptor = NULL;
    *acl = NULL;
    *token_user = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
        return map_win_error(GetLastError());
    GetTokenInformation(token, TokenUser, NULL, 0, &required);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || !required) {
        CloseHandle(token);
        return map_win_error(GetLastError());
    }
    *token_user = malloc(required);
    if (!*token_user || !GetTokenInformation(token, TokenUser, *token_user, required, &required)) {
        DWORD error = *token_user ? GetLastError() : ERROR_NOT_ENOUGH_MEMORY;
        free(*token_user);
        *token_user = NULL;
        CloseHandle(token);
        return map_win_error(error);
    }
    CloseHandle(token);
    if (!CreateWellKnownSid(WinLocalSystemSid, NULL, system_sid, &system_sid_size))
        goto fail;
    DWORD acl_size = sizeof(ACL) +
        2 * (sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD)) +
        GetLengthSid(((TOKEN_USER *)*token_user)->User.Sid) + system_sid_size;
    *acl = malloc(acl_size);
    *descriptor = malloc(SECURITY_DESCRIPTOR_MIN_LENGTH);
    if (!*acl || !*descriptor || !InitializeAcl(*acl, acl_size, ACL_REVISION) ||
        !AddAccessAllowedAceEx(*acl, ACL_REVISION, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
                              GENERIC_ALL, ((TOKEN_USER *)*token_user)->User.Sid) ||
        !AddAccessAllowedAceEx(*acl, ACL_REVISION, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
                              GENERIC_ALL, system_sid) ||
        !InitializeSecurityDescriptor(*descriptor, SECURITY_DESCRIPTOR_REVISION) ||
        !SetSecurityDescriptorDacl(*descriptor, TRUE, *acl, FALSE))
        goto fail;
    attributes->nLength = sizeof(*attributes);
    attributes->lpSecurityDescriptor = *descriptor;
    attributes->bInheritHandle = FALSE;
    return 0;
fail:
    free(*acl);
    free(*descriptor);
    free(*token_user);
    *acl = NULL;
    *descriptor = NULL;
    *token_user = NULL;
    errno = EACCES;
    return -1;
}

static void private_security_free(PSECURITY_DESCRIPTOR descriptor, PACL acl,
                                  PTOKEN_USER token_user) {
    free(acl);
    free(descriptor);
    free(token_user);
}

static int random_suffix(char *out) {
    static const char hex[] = "0123456789abcdef";
    unsigned char random[CAT_WIN_TEMP_CHARS / 2];
    NTSTATUS status = BCryptGenRandom(NULL, random, sizeof(random), BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status < 0) {
        errno = EIO;
        return -1;
    }
    for (size_t i = 0; i < sizeof(random); i++) {
        out[i * 2] = hex[random[i] >> 4];
        out[i * 2 + 1] = hex[random[i] & 15];
    }
    return 0;
}

static int map_win_error(DWORD error) {
    switch (error) {
    case ERROR_FILE_NOT_FOUND:
    case ERROR_PATH_NOT_FOUND: errno = ENOENT; break;
    case ERROR_ALREADY_EXISTS:
    case ERROR_FILE_EXISTS: errno = EEXIST; break;
    case ERROR_ACCESS_DENIED:
    case ERROR_SHARING_VIOLATION: errno = EACCES; break;
    case ERROR_DIRECTORY: errno = ENOTDIR; break;
    case ERROR_DIR_NOT_EMPTY: errno = ENOTEMPTY; break;
    case ERROR_INVALID_NAME:
    case ERROR_INVALID_PARAMETER: errno = EINVAL; break;
    case ERROR_NOT_SUPPORTED:
    case ERROR_INVALID_FUNCTION: errno = ENOTSUP; break;
    case ERROR_TOO_MANY_OPEN_FILES: errno = EMFILE; break;
    case ERROR_NOT_ENOUGH_MEMORY: errno = ENOMEM; break;
    case ERROR_DISK_FULL: errno = ENOSPC; break;
    default: errno = EIO; break;
    }
    return -1;
}

static int map_nt_status(NTSTATUS status) {
    ULONG error = RtlNtStatusToDosError(status);
    switch (error) {
    case ERROR_FILE_NOT_FOUND:
    case ERROR_PATH_NOT_FOUND: errno = ENOENT; break;
    case ERROR_ALREADY_EXISTS: errno = EEXIST; break;
    case ERROR_ACCESS_DENIED: errno = EACCES; break;
    case ERROR_DIRECTORY: errno = ENOTDIR; break;
    case ERROR_DIR_NOT_EMPTY: errno = ENOTEMPTY; break;
    case ERROR_REPARSE_TAG_INVALID: errno = ELOOP; break;
    case ERROR_CANT_RESOLVE_FILENAME: errno = ELOOP; break;
    case ERROR_INVALID_NAME:
    case ERROR_INVALID_PARAMETER: errno = EINVAL; break;
    case ERROR_NOT_SUPPORTED:
    case ERROR_INVALID_FUNCTION: errno = ENOTSUP; break;
    default: errno = EIO; break;
    }
    return -1;
}

static wchar_t *utf8_to_wide(const char *s) {
    int n;
    wchar_t *wide;
    if (!s || (n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0)) <= 0) {
        errno = EILSEQ;
        return NULL;
    }
    wide = malloc((size_t)n * sizeof(*wide));
    if (!wide) {
        errno = ENOMEM;
        return NULL;
    }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, wide, n)) {
        free(wide);
        errno = EILSEQ;
        return NULL;
    }
    return wide;
}

static char *wide_to_utf8(const wchar_t *s, size_t length) {
    if (length > INT_MAX) {
        errno = ENAMETOOLONG;
        return NULL;
    }
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s, (int)length,
                                NULL, 0, NULL, NULL);
    if (n <= 0 || (size_t)n >= sizeof(((struct dirent *)0)->d_name)) {
        errno = ENAMETOOLONG;
        return NULL;
    }
    char *out = malloc((size_t)n + 1);
    if (!out) {
        errno = ENOMEM;
        return NULL;
    }
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s, (int)length,
                             out, n, NULL, NULL)) {
        free(out);
        errno = EILSEQ;
        return NULL;
    }
    out[n] = 0;
    return out;
}

static int filetime_seconds(FILETIME ft, time_t *out) {
    ULARGE_INTEGER t;
    t.LowPart = ft.dwLowDateTime;
    t.HighPart = ft.dwHighDateTime;
    if (t.QuadPart < UINT64_C(116444736000000000)) {
        *out = 0;
        return 0;
    }
    t.QuadPart -= UINT64_C(116444736000000000);
    *out = (time_t)(t.QuadPart / UINT64_C(10000000));
    return 0;
}

static int stat_handle(HANDLE handle, struct stat *st) {
    BY_HANDLE_FILE_INFORMATION info;
    FILE_BASIC_INFO basic;
    memset(st, 0, sizeof(*st));
    if (!GetFileInformationByHandle(handle, &info))
        return map_win_error(GetLastError());
    st->st_dev = (dev_t)info.dwVolumeSerialNumber;
    st->st_ino = (ino_t)(((uint64_t)info.nFileIndexHigh << 32) | info.nFileIndexLow);
    st->st_nlink = info.nNumberOfLinks;
    st->st_size = (off_t)(((uint64_t)info.nFileSizeHigh << 32) | info.nFileSizeLow);
    st->st_mode = (mode_t)(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY
                               ? S_IFDIR | 0755
                               : S_IFREG | 0644);
    if (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
        st->st_mode = (mode_t)(S_IFLNK | 0777);
    filetime_seconds(info.ftCreationTime, &st->st_ctime);
    filetime_seconds(info.ftLastWriteTime, &st->st_mtime);
    if (GetFileInformationByHandleEx(handle, FileBasicInfo, &basic, sizeof(basic))) {
        /* MinGW's struct stat only keeps seconds. st_atime is private to CAT's
         * Win32 mutation snapshot, so retain a high-resolution timestamp
         * fingerprint there. */
        uint64_t write = (uint64_t)basic.LastWriteTime.QuadPart;
        uint64_t change = (uint64_t)basic.ChangeTime.QuadPart;
        uint64_t fingerprint = write ^ ((change << 23) | (change >> 41));
        st->st_atime = (time_t)(fingerprint & INT64_MAX);
        st->st_ctime = (time_t)(change / UINT64_C(10000000));
    } else {
        st->st_atime = 0;
    }
    return 0;
}

static HANDLE handle_from_fd(int fd) {
    intptr_t raw = _get_osfhandle(fd);
    if (raw == -1) {
        errno = EBADF;
        return INVALID_HANDLE_VALUE;
    }
    return (HANDLE)raw;
}

static int fd_from_handle(HANDLE handle, int flags) {
    int mode = _O_BINARY;
    if ((flags & O_RDWR) == O_RDWR)
        mode |= _O_RDWR;
    else if (flags & O_WRONLY)
        mode |= _O_WRONLY;
    else
        mode |= _O_RDONLY;
    int fd = _open_osfhandle((intptr_t)handle, mode);
    if (fd < 0) {
        CloseHandle(handle);
        errno = EMFILE;
    }
    return fd;
}

static HANDLE open_relative_handle(int parent, const char *name, int flags,
                                   ACCESS_MASK extra_access, int allow_reparse) {
    HANDLE root = handle_from_fd(parent), result = INVALID_HANDLE_VALUE;
    wchar_t *wide = utf8_to_wide(name);
    if (root == INVALID_HANDLE_VALUE || !wide) {
        free(wide);
        return INVALID_HANDLE_VALUE;
    }
    size_t units = wcslen(wide);
    if (!units || wcschr(wide, L'\\') || wcschr(wide, L'/') || units > USHRT_MAX / sizeof(wchar_t)) {
        free(wide);
        errno = EINVAL;
        return INVALID_HANDLE_VALUE;
    }
    UNICODE_STRING object_name;
    object_name.Buffer = wide;
    object_name.Length = (USHORT)(units * sizeof(wchar_t));
    object_name.MaximumLength = object_name.Length;
    OBJECT_ATTRIBUTES attributes;
    SECURITY_ATTRIBUTES security = {0};
    PSECURITY_DESCRIPTOR descriptor = NULL;
    PACL acl = NULL;
    PTOKEN_USER token_user = NULL;
    if ((flags & O_CREAT) && private_security(&security, &descriptor, &acl, &token_user)) {
        free(wide);
        return INVALID_HANDLE_VALUE;
    }
    InitializeObjectAttributes(&attributes, &object_name,
                               OBJ_CASE_INSENSITIVE | (allow_reparse ? 0 : OBJ_DONT_REPARSE),
                               root, (flags & O_CREAT) ? descriptor : NULL);
    ACCESS_MASK access = FILE_READ_ATTRIBUTES | SYNCHRONIZE | extra_access;
    ULONG disposition = FILE_OPEN;
    if (flags & O_CREAT)
        disposition = flags & O_EXCL ? FILE_CREATE : (flags & O_TRUNC ? FILE_OVERWRITE_IF : FILE_OPEN_IF);
    else if (flags & O_TRUNC)
        disposition = FILE_OVERWRITE;
    if (flags & O_WRONLY)
        access |= GENERIC_WRITE;
    else if (flags & O_RDWR)
        access |= GENERIC_READ | GENERIC_WRITE;
    else if (flags & O_DIRECTORY)
        access |= FILE_LIST_DIRECTORY | FILE_TRAVERSE;
    else if (!allow_reparse)
        access |= GENERIC_READ;
    ULONG options = FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT;
    if (flags & O_DIRECTORY)
        options |= FILE_DIRECTORY_FILE;
    else if (!(flags & O_CREAT) && (flags & O_NONBLOCK))
        options |= FILE_NON_DIRECTORY_FILE;
    IO_STATUS_BLOCK io;
    NTSTATUS status = NtCreateFile(&result, access, &attributes, &io, NULL,
                                   (flags & O_DIRECTORY) ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL,
                                   FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                   disposition, options, NULL, 0);
    private_security_free(descriptor, acl, token_user);
    free(wide);
    if (!NT_SUCCESS(status)) {
        map_nt_status(status);
        return INVALID_HANDLE_VALUE;
    }
    BY_HANDLE_FILE_INFORMATION info;
    if (!GetFileInformationByHandle(result, &info)) {
        DWORD error = GetLastError();
        CloseHandle(result);
        map_win_error(error);
        return INVALID_HANDLE_VALUE;
    }
    if (!allow_reparse && (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
        CloseHandle(result);
        errno = ELOOP;
        return INVALID_HANDLE_VALUE;
    }
    if ((flags & O_DIRECTORY) && !(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
        CloseHandle(result);
        errno = ENOTDIR;
        return INVALID_HANDLE_VALUE;
    }
    return result;
}

static HANDLE open_path_handle(const char *path, int flags, int allow_reparse) {
    wchar_t *wide = utf8_to_wide(path);
    if (!wide)
        return INVALID_HANDLE_VALUE;
    DWORD access = FILE_READ_ATTRIBUTES;
    if (flags & O_WRONLY)
        access |= GENERIC_WRITE;
    else if (flags & O_RDWR)
        access |= GENERIC_READ | GENERIC_WRITE;
    else if (flags & O_DIRECTORY)
        access |= FILE_LIST_DIRECTORY | FILE_TRAVERSE;
    else if (!allow_reparse)
        access |= GENERIC_READ;
    DWORD disposition = OPEN_EXISTING;
    if (flags & O_CREAT)
        disposition = flags & O_EXCL ? CREATE_NEW : (flags & O_TRUNC ? CREATE_ALWAYS : OPEN_ALWAYS);
    else if (flags & O_TRUNC)
        disposition = TRUNCATE_EXISTING;
    DWORD attributes = FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT;
    if (flags & O_DIRECTORY)
        attributes |= FILE_FLAG_BACKUP_SEMANTICS;
    SECURITY_ATTRIBUTES security = {0};
    PSECURITY_DESCRIPTOR descriptor = NULL;
    PACL acl = NULL;
    PTOKEN_USER token_user = NULL;
    if ((flags & O_CREAT) && private_security(&security, &descriptor, &acl, &token_user)) {
        free(wide);
        return INVALID_HANDLE_VALUE;
    }
    HANDLE handle = CreateFileW(wide, access,
                                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                (flags & O_CREAT) ? &security : NULL,
                                disposition, attributes, NULL);
    DWORD error = GetLastError();
    free(wide);
    private_security_free(descriptor, acl, token_user);
    if (handle == INVALID_HANDLE_VALUE) {
        map_win_error(error);
        return handle;
    }
    BY_HANDLE_FILE_INFORMATION info;
    if (!GetFileInformationByHandle(handle, &info)) {
        error = GetLastError();
        CloseHandle(handle);
        map_win_error(error);
        return INVALID_HANDLE_VALUE;
    }
    if (!allow_reparse && (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
        CloseHandle(handle);
        errno = ELOOP;
        return INVALID_HANDLE_VALUE;
    }
    if ((flags & O_DIRECTORY) && !(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
        CloseHandle(handle);
        errno = ENOTDIR;
        return INVALID_HANDLE_VALUE;
    }
    if (!(flags & O_DIRECTORY) && !(flags & O_CREAT) &&
        (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
        CloseHandle(handle);
        errno = EISDIR;
        return INVALID_HANDLE_VALUE;
    }
    return handle;
}

int cat_win_open(const char *path, int flags, ...) {
    HANDLE handle = open_path_handle(path, flags, 0);
    return handle == INVALID_HANDLE_VALUE ? -1 : fd_from_handle(handle, flags);
}

int cat_win_openat(int parent, const char *path, int flags, ...) {
    HANDLE handle = open_relative_handle(parent, path, flags, 0, 0);
    return handle == INVALID_HANDLE_VALUE ? -1 : fd_from_handle(handle, flags);
}

int cat_win_close(int fd) { return _close(fd); }
int cat_win_dup(int fd) { return _dup(fd); }

int cat_win_fstat(int fd, struct stat *st) {
    HANDLE handle = handle_from_fd(fd);
    return handle == INVALID_HANDLE_VALUE ? -1 : stat_handle(handle, st);
}

int cat_win_fstatat(int parent, const char *path, struct stat *st, int flags) {
    (void)flags;
    HANDLE handle = open_relative_handle(parent, path, O_RDONLY, FILE_READ_ATTRIBUTES, 1);
    if (handle == INVALID_HANDLE_VALUE)
        return -1;
    int rc = stat_handle(handle, st);
    CloseHandle(handle);
    return rc;
}

int cat_win_lstat(const char *path, struct stat *st) {
    HANDLE handle = open_path_handle(path, O_RDONLY, 1);
    if (handle == INVALID_HANDLE_VALUE)
        return -1;
    int rc = stat_handle(handle, st);
    CloseHandle(handle);
    return rc;
}

int cat_win_mkdir(const char *path, int mode) {
    (void)mode;
    wchar_t *wide = utf8_to_wide(path);
    if (!wide)
        return -1;
    SECURITY_ATTRIBUTES security = {0};
    PSECURITY_DESCRIPTOR descriptor = NULL;
    PACL acl = NULL;
    PTOKEN_USER token_user = NULL;
    if (private_security(&security, &descriptor, &acl, &token_user)) {
        free(wide);
        return -1;
    }
    BOOL ok = CreateDirectoryW(wide, &security);
    DWORD error = GetLastError();
    free(wide);
    private_security_free(descriptor, acl, token_user);
    return ok ? 0 : map_win_error(error);
}

int cat_win_mkdirat(int parent, const char *path, int mode) {
    (void)mode;
    HANDLE handle = open_relative_handle(parent, path, O_CREAT | O_EXCL | O_DIRECTORY,
                                         FILE_LIST_DIRECTORY | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY,
                                         0);
    if (handle == INVALID_HANDLE_VALUE)
        return -1;
    CloseHandle(handle);
    return 0;
}

int cat_win_unlinkat(int parent, const char *path, int flags) {
    HANDLE handle = open_relative_handle(parent, path, O_RDONLY, DELETE | FILE_READ_ATTRIBUTES, 1);
    if (handle == INVALID_HANDLE_VALUE)
        return -1;
    struct stat st;
    if (stat_handle(handle, &st)) {
        CloseHandle(handle);
        return -1;
    }
    if (!!S_ISDIR(st.st_mode) != !!(flags & AT_REMOVEDIR)) {
        CloseHandle(handle);
        errno = flags & AT_REMOVEDIR ? ENOTDIR : EISDIR;
        return -1;
    }
    FILE_DISPOSITION_INFO disposition = {TRUE};
    BOOL ok = SetFileInformationByHandle(handle, FileDispositionInfo,
                                         &disposition, sizeof(disposition));
    DWORD error = GetLastError();
    CloseHandle(handle);
    return ok ? 0 : map_win_error(error);
}

int cat_win_unlink(const char *path) {
    wchar_t *wide = utf8_to_wide(path);
    if (!wide)
        return -1;
    BOOL ok = DeleteFileW(wide);
    DWORD error = GetLastError();
    free(wide);
    return ok ? 0 : map_win_error(error);
}

int cat_win_rmdir(const char *path) {
    wchar_t *wide = utf8_to_wide(path);
    if (!wide)
        return -1;
    BOOL ok = RemoveDirectoryW(wide);
    DWORD error = GetLastError();
    free(wide);
    return ok ? 0 : map_win_error(error);
}

int cat_win_rename(const char *source, const char *destination) {
    wchar_t *src = utf8_to_wide(source), *dst = utf8_to_wide(destination);
    if (!src || !dst) {
        free(src);
        free(dst);
        return -1;
    }
    BOOL ok = MoveFileW(src, dst); /* MoveFileW never replaces an existing target. */
    DWORD error = GetLastError();
    free(src);
    free(dst);
    return ok ? 0 : map_win_error(error);
}

int cat_win_mkstemp(char *path) {
    size_t length = strlen(path);
    if (length < CAT_WIN_TEMP_CHARS || memcmp(path + length - CAT_WIN_TEMP_CHARS,
                                               CAT_WIN_TEMP_TEMPLATE, CAT_WIN_TEMP_CHARS)) {
        errno = EINVAL;
        return -1;
    }
    for (unsigned attempt = 0; attempt < 256; attempt++) {
        if (random_suffix(path + length - CAT_WIN_TEMP_CHARS))
            return -1;
        int fd = cat_win_open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
        if (fd >= 0)
            return fd;
        if (errno != EEXIST)
            return -1;
    }
    errno = EEXIST;
    return -1;
}

char *cat_win_mkdtemp(char *path) {
    size_t length = strlen(path);
    if (length < CAT_WIN_TEMP_CHARS || memcmp(path + length - CAT_WIN_TEMP_CHARS,
                                               CAT_WIN_TEMP_TEMPLATE, CAT_WIN_TEMP_CHARS)) {
        errno = EINVAL;
        return NULL;
    }
    for (unsigned attempt = 0; attempt < 256; attempt++) {
        if (random_suffix(path + length - CAT_WIN_TEMP_CHARS))
            return NULL;
        if (!cat_win_mkdir(path, 0700))
            return path;
        if (errno != EEXIST)
            return NULL;
    }
    errno = EEXIST;
    return NULL;
}

int cat_win_fchmod(int fd, unsigned mode) { (void)fd; (void)mode; return 0; }
int cat_win_fchmodat(int parent, const char *path, unsigned mode, int flags) {
    (void)parent; (void)path; (void)mode; (void)flags; return 0;
}
int cat_win_fsync(int fd) {
    HANDLE handle = handle_from_fd(fd);
    if (handle == INVALID_HANDLE_VALUE)
        return -1;
    if (FlushFileBuffers(handle))
        return 0;
    DWORD error = GetLastError();
    if (error == ERROR_INVALID_FUNCTION || error == ERROR_ACCESS_DENIED) {
        errno = ENOTSUP;
        return -1;
    }
    return map_win_error(error);
}

int cat_win_temp_directory(char *buffer, size_t capacity) {
    DWORD needed = GetTempPathW(0, NULL);
    if (!needed || needed >= 32768)
        return map_win_error(GetLastError());
    wchar_t *wide = malloc(((size_t)needed + 1) * sizeof(*wide));
    if (!wide)
        return map_win_error(ERROR_NOT_ENOUGH_MEMORY);
    DWORD length = GetTempPathW(needed + 1, wide);
    if (!length || length > needed) {
        DWORD error = GetLastError();
        free(wide);
        return map_win_error(error);
    }
    int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, (int)length,
                                    buffer, (int)capacity, NULL, NULL);
    free(wide);
    if (!bytes || (size_t)bytes >= capacity) {
        errno = ENAMETOOLONG;
        return -1;
    }
    buffer[bytes] = 0;
    return 0;
}

DIR *cat_win_fdopendir(int fd) {
    HANDLE handle = handle_from_fd(fd);
    if (handle == INVALID_HANDLE_VALUE)
        return NULL;
    struct cat_win_dir *dir = calloc(1, sizeof(*dir));
    if (!dir)
        return NULL;
    dir->handle = handle;
    dir->fd = fd;
    dir->first = 1;
    dir->valid = 0;
    /* fdopendir takes ownership of the descriptor, matching the POSIX contract. */
    return dir;
}

struct dirent *cat_win_readdir(DIR *opaque) {
    struct cat_win_dir *dir = opaque;
    if (!dir || dir->finished)
        return NULL;
    for (;;) {
        if (dir->offset >= dir->valid) {
            FILE_INFO_BY_HANDLE_CLASS cls = dir->first ? FileIdBothDirectoryRestartInfo
                                                       : FileIdBothDirectoryInfo;
            dir->first = 0;
            if (!GetFileInformationByHandleEx(dir->handle, cls, dir->buffer,
                                              sizeof(dir->buffer))) {
                DWORD error = GetLastError();
                if (error == ERROR_NO_MORE_FILES || error == ERROR_FILE_NOT_FOUND) {
                    dir->finished = 1;
                    return NULL;
                }
                map_win_error(error);
                dir->finished = 1;
                return NULL;
            }
            dir->valid = sizeof(dir->buffer);
            dir->offset = 0;
        }
        FILE_ID_BOTH_DIR_INFORMATION *item =
            (FILE_ID_BOTH_DIR_INFORMATION *)(dir->buffer + dir->offset);
        if (item->FileNameLength % sizeof(wchar_t)) {
            errno = EIO;
            dir->finished = 1;
            return NULL;
        }
        size_t units = item->FileNameLength / sizeof(wchar_t);
        char *name = wide_to_utf8(item->FileName, units);
        if (!name) {
            dir->finished = 1;
            return NULL;
        }
        size_t bytes = strlen(name);
        memcpy(dir->entry.d_name, name, bytes + 1);
        free(name);
        ULONG next = item->NextEntryOffset;
        if (!next) {
            dir->offset = dir->valid;
            /* Next call asks the kernel for the next batch. */
        } else if (next > dir->valid - dir->offset) {
            errno = EIO;
            dir->finished = 1;
            return NULL;
        } else {
            dir->offset += next;
        }
        return &dir->entry;
    }
}

int cat_win_closedir(DIR *opaque) {
    struct cat_win_dir *dir = opaque;
    if (!dir)
        return 0;
    int rc = _close(dir->fd);
    free(dir);
    return rc;
}
