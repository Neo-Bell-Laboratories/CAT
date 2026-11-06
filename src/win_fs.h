#ifndef CAT_WIN_FS_H
#define CAT_WIN_FS_H

#ifdef _WIN32

#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>

#define CAT_WIN_TEMP_TEMPLATE "XXXXXXXXXXXXXXXX"
#define CAT_WIN_TEMP_CHARS 16u

/* Private flags used by catc.c to retain its POSIX-like call sites. */
#ifndef O_DIRECTORY
#define O_DIRECTORY 0x10000000
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0x20000000
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0x40000000
#endif
#ifndef O_NONBLOCK
#define O_NONBLOCK 0x08000000
#endif
#ifndef O_NOCTTY
#define O_NOCTTY 0x04000000
#endif
#ifndef AT_SYMLINK_NOFOLLOW
#define AT_SYMLINK_NOFOLLOW 0x100
#endif
#ifndef AT_REMOVEDIR
#define AT_REMOVEDIR 0x200
#endif

struct dirent {
    char d_name[4096];
};
typedef struct cat_win_dir DIR;

int cat_win_open(const char *path, int flags, ...);
int cat_win_openat(int parent, const char *path, int flags, ...);
int cat_win_close(int fd);
int cat_win_dup(int fd);
int cat_win_fstat(int fd, struct stat *st);
int cat_win_fstatat(int parent, const char *path, struct stat *st, int flags);
int cat_win_lstat(const char *path, struct stat *st);
int cat_win_mkdir(const char *path, int mode);
int cat_win_mkdirat(int parent, const char *path, int mode);
int cat_win_unlink(const char *path);
int cat_win_rmdir(const char *path);
int cat_win_unlinkat(int parent, const char *path, int flags);
int cat_win_rename(const char *source, const char *destination);
int cat_win_mkstemp(char *path);
char *cat_win_mkdtemp(char *path);
int cat_win_fchmod(int fd, unsigned mode);
int cat_win_fchmodat(int parent, const char *path, unsigned mode, int flags);
int cat_win_fsync(int fd);
int cat_win_temp_directory(char *buffer, size_t capacity);
DIR *cat_win_fdopendir(int fd);
struct dirent *cat_win_readdir(DIR *dir);
int cat_win_closedir(DIR *dir);

#define open cat_win_open
#define openat cat_win_openat
#define close cat_win_close
#define dup cat_win_dup
#define fstat cat_win_fstat
#define fstatat cat_win_fstatat
#define lstat cat_win_lstat
#define mkdir(path, mode) cat_win_mkdir(path, mode)
#define mkdirat cat_win_mkdirat
#define unlink cat_win_unlink
#define rmdir cat_win_rmdir
#define unlinkat cat_win_unlinkat
#define rename cat_win_rename
#define mkstemp cat_win_mkstemp
#define mkdtemp cat_win_mkdtemp
#define fchmod cat_win_fchmod
#define fchmodat cat_win_fchmodat
#define read _read
#define write _write
#define lseek _lseeki64
#define fsync cat_win_fsync
#define fdopendir cat_win_fdopendir
#define readdir cat_win_readdir
#define closedir cat_win_closedir

#endif
#endif
