#include "xf.h"
#include <stdio.h>

int main(void) {
    /* Repeated lifecycles exercise ownership and runtime teardown. */
    for (int i = 0; i < 3; ++i) {
        xf_State *xf = xf_newstate();
        if (!xf) {
            fputs("xf_newstate failed\n", stderr);
            return 1;
        }
        int status = xf_set_max_jobs(xf, 1);
        if (!status) {
            status = xf_run_string(xf,
                "BEGIN {\n"
                " str result = core.lambda.eval(\"I cat_smoke_ok\")\n"
                " print result\n"
                "}\n", "cat-smoke");
        }
        if (status || xf_had_error(xf)) {
            fprintf(stderr, "XF smoke failed: %s\n", xf_last_error(xf));
            xf_close(xf);
            return 1;
        }
        xf_close(xf);
    }
    printf("PASS: static XF %s and native LambdaScript bridge\n", xf_version());
    return 0;
}
