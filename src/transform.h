#ifndef CAT_TRANSFORM_H
#define CAT_TRANSFORM_H

/* Source compatibility for older in-tree consumers. New integrations should
 * include <cats/transform.h> from the installed public API. */
#include <cats/transform.h>
#define CAT_BLOCK_MAX CATS_BLOCK_MAX
#define CAT_BLOCK_V02_MAX CATS_BLOCK_V02_MAX
#define CAT_BLOCK_V01_MAX CATS_BLOCK_V01_MAX

#endif
