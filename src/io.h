#ifndef CAT_IO_H
#define CAT_IO_H
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
/* At most eight anonymous disk spools. Size accounting covers their aggregate
 * logical lengths; output staging and final output have separate bounds. */
typedef struct {
    int fd;
    uint64_t size;
} cat_spool;
extern volatile sig_atomic_t cat_cancelled;
extern uint64_t cat_temp_limit;
extern char cat_error[512];
int cat_fail(const char *message);
int cat_syserr(const char *operation);
int cat_io_init(int install_signals);
int cat_check_cancel(void);
cat_spool *cat_spool_new(void);
void cat_spool_close(cat_spool *spool);
void cat_spools_close(void);
int cat_seek(int fd, uint64_t offset);
int cat_read(int fd, void *data, size_t n);
int cat_write(int fd, const void *data, size_t n);
int cat_temp_claim(uint64_t n);
void cat_temp_release(uint64_t n);
int cat_spool_write(cat_spool *spool, const void *data, size_t n);
int cat_copy(int source, cat_spool *dest, uint64_t n);
int cat_sync(int fd, int directory);
void cat_test_hook(const char *stage);
#endif
