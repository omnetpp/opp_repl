// The file trace of the test map (opp_repl.test.test_map): an LD_PRELOAD library that writes one
// line "<op> <ok|fail> <path>" for each file open ("open" for input, "write" for an open that
// only writes or truncates), examination (stat, access, readlink, realpath) and directory listing
// (opendir, an open with O_DIRECTORY, glob) of the process to the file
// $OPP_REPL_FILE_TRACE.<pid>. The library follows chdir and fchdir and writes absolute paths; only
// a path relative to a directory file descriptor stays relative ("openat", "statat"). For glob,
// the path is the pattern. opp_repl compiles it: cc -O2 -shared -fPIC -o <lib> filetrace.c -ldl
#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <glob.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int trace_fd = -1;
static __thread int busy = 0;
static char cwd[4096] = "";

static void update_cwd(void)
{
    if (!getcwd(cwd, sizeof(cwd)))
        cwd[0] = 0;
}

static void *real(const char *name)
{
    return dlsym(RTLD_NEXT, name);
}

__attribute__((constructor)) static void filetrace_init(void)
{
    const char *base = getenv("OPP_REPL_FILE_TRACE");
    if (!base)
        return;
    char path[4096];
    snprintf(path, sizeof(path), "%s.%d", base, getpid());
    int (*real_open)(const char *, int, ...) = real("open");
    trace_fd = real_open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    update_cwd();
}

// the op of an open: a listing, an open that only writes or truncates (an output), or an input
static const char *open_op(int flags)
{
    if (flags & O_DIRECTORY)
        return "list";
    if ((flags & O_ACCMODE) == O_WRONLY || (flags & O_TRUNC))
        return "write";
    return "open";
}

static const char *fopen_op(const char *mode)
{
    return mode && (mode[0] == 'w' || (mode[0] == 'a' && !strchr(mode, '+'))) ? "write" : "open";
}

static void trace(const char *op, const char *path, int ok)
{
    if (trace_fd < 0 || !path || busy)
        return;
    busy = 1;
    int saved = errno;
    char line[8400];
    int relative = path[0] != '/' && strcmp(op, "openat") && strcmp(op, "statat");
    int n = snprintf(line, sizeof(line), "%s %s %s%s%s\n", op, ok ? "ok" : "fail", relative ? cwd : "", relative ? "/" : "", path);
    if (n > 0)
        if (write(trace_fd, line, n < (int)sizeof(line) ? n : (int)sizeof(line) - 1) < 0)
            ; // a trace line that the disk refuses is lost; the run must go on
    errno = saved;
    busy = 0;
}

#define OPEN_LIKE(NAME)                                                     \
    int NAME(const char *path, int flags, ...)                              \
    {                                                                       \
        static int (*f)(const char *, int, ...);                            \
        if (!f) f = real(#NAME);                                            \
        mode_t mode = 0;                                                    \
        if (flags & (O_CREAT | O_TMPFILE)) {                                \
            va_list ap; va_start(ap, flags); mode = va_arg(ap, mode_t); va_end(ap); \
        }                                                                   \
        int r = f(path, flags, mode);                                       \
        trace(open_op(flags), path, r >= 0);                                \
        return r;                                                           \
    }
OPEN_LIKE(open)
OPEN_LIKE(open64)

#define OPENAT_LIKE(NAME)                                                   \
    int NAME(int dirfd, const char *path, int flags, ...)                   \
    {                                                                       \
        static int (*f)(int, const char *, int, ...);                       \
        if (!f) f = real(#NAME);                                            \
        mode_t mode = 0;                                                    \
        if (flags & (O_CREAT | O_TMPFILE)) {                                \
            va_list ap; va_start(ap, flags); mode = va_arg(ap, mode_t); va_end(ap); \
        }                                                                   \
        int r = f(dirfd, path, flags, mode);                                \
        trace(dirfd == AT_FDCWD || path[0] == '/' ? open_op(flags) : "openat", path, r >= 0); \
        return r;                                                           \
    }
OPENAT_LIKE(openat)
OPENAT_LIKE(openat64)

int __open_2(const char *path, int flags)
{
    static int (*f)(const char *, int);
    if (!f) f = real("__open_2");
    int r = f(path, flags);
    trace(open_op(flags), path, r >= 0);
    return r;
}

int __open64_2(const char *path, int flags)
{
    static int (*f)(const char *, int);
    if (!f) f = real("__open64_2");
    int r = f(path, flags);
    trace(open_op(flags), path, r >= 0);
    return r;
}

#define FOPEN_LIKE(NAME)                                                    \
    FILE *NAME(const char *path, const char *mode)                          \
    {                                                                       \
        static FILE *(*f)(const char *, const char *);                      \
        if (!f) f = real(#NAME);                                            \
        FILE *r = f(path, mode);                                            \
        trace(fopen_op(mode), path, r != NULL);                             \
        return r;                                                           \
    }
FOPEN_LIKE(fopen)
FOPEN_LIKE(fopen64)

#define STAT_LIKE(NAME, T)                                                  \
    int NAME(const char *path, T *buf)                                      \
    {                                                                       \
        static int (*f)(const char *, T *);                                 \
        if (!f) f = real(#NAME);                                            \
        int r = f(path, buf);                                               \
        trace("stat", path, r == 0);                                        \
        return r;                                                           \
    }
STAT_LIKE(stat, struct stat)
STAT_LIKE(stat64, struct stat64)
STAT_LIKE(lstat, struct stat)
STAT_LIKE(lstat64, struct stat64)

int fstatat(int dirfd, const char *path, struct stat *buf, int flags)
{
    static int (*f)(int, const char *, struct stat *, int);
    if (!f) f = real("fstatat");
    int r = f(dirfd, path, buf, flags);
    if (path && path[0])
        trace(dirfd == AT_FDCWD || path[0] == '/' ? "stat" : "statat", path, r == 0);
    return r;
}

int fstatat64(int dirfd, const char *path, struct stat64 *buf, int flags)
{
    static int (*f)(int, const char *, struct stat64 *, int);
    if (!f) f = real("fstatat64");
    int r = f(dirfd, path, buf, flags);
    if (path && path[0])
        trace(dirfd == AT_FDCWD || path[0] == '/' ? "stat" : "statat", path, r == 0);
    return r;
}

int statx(int dirfd, const char *path, int flags, unsigned int mask, struct statx *buf)
{
    static int (*f)(int, const char *, int, unsigned int, struct statx *);
    if (!f) f = real("statx");
    int r = f(dirfd, path, flags, mask, buf);
    if (path && path[0])
        trace(dirfd == AT_FDCWD || path[0] == '/' ? "stat" : "statat", path, r == 0);
    return r;
}

int access(const char *path, int mode)
{
    static int (*f)(const char *, int);
    if (!f) f = real("access");
    int r = f(path, mode);
    trace("access", path, r == 0);
    return r;
}

int faccessat(int dirfd, const char *path, int mode, int flags)
{
    static int (*f)(int, const char *, int, int);
    if (!f) f = real("faccessat");
    int r = f(dirfd, path, mode, flags);
    trace("access", path, r == 0);
    return r;
}

DIR *opendir(const char *path)
{
    static DIR *(*f)(const char *);
    if (!f) f = real("opendir");
    DIR *r = f(path);
    trace("list", path, r != NULL);
    return r;
}

int chdir(const char *path)
{
    static int (*f)(const char *);
    if (!f) f = real("chdir");
    int r = f(path);
    trace("chdir", path, r == 0);
    if (r == 0)
        update_cwd();
    return r;
}

int fchdir(int fd)
{
    static int (*f)(int);
    if (!f) f = real("fchdir");
    int r = f(fd);
    if (r == 0)
        update_cwd();
    return r;
}

int glob(const char *pattern, int flags, int (*errfunc)(const char *, int), glob_t *pglob)
{
    static int (*f)(const char *, int, int (*)(const char *, int), glob_t *);
    if (!f) f = real("glob");
    int r = f(pattern, flags, errfunc, pglob);
    trace("glob", pattern, r == 0);
    return r;
}

ssize_t readlink(const char *path, char *buf, size_t size)
{
    static ssize_t (*f)(const char *, char *, size_t);
    if (!f) f = real("readlink");
    ssize_t r = f(path, buf, size);
    trace("stat", path, r >= 0);
    return r;
}

char *realpath(const char *path, char *resolved)
{
    static char *(*f)(const char *, char *);
    if (!f) f = real("realpath");
    char *r = f(path, resolved);
    trace("stat", path, r != NULL);
    return r;
}
