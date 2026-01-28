#include <stdio.h>
#include <stdlib.h>

void __attribute__((constructor)) init(void) {
  fprintf(stderr, "[MOCK_CLEAN_EXIT] Calling exit(0)...\n");
  exit(0);
}
