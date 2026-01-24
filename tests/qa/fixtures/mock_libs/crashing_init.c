#include <stdio.h>
#include <stdlib.h>

void __attribute__((constructor)) init(void) {
  // Crashing intentionally to test Velo's Death Pact isolation
  fprintf(stderr, "[MOCK_LIB] Triggering intentional SEGV...\n");
  int *p = NULL;
  *p = 42;
}
