#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

void __attribute__((constructor)) init(void) {
  FILE *f = fopen(".preloaded_proof", "w");
  if (f) {
    fprintf(f, "preloaded");
    fclose(f);
  }
}
