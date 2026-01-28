#include <stdio.h>
#include <unistd.h>

void __attribute__((constructor)) init(void) {
  // Infinite loop intentionally to test Velo's Death Pact timeout
  fprintf(stderr, "[MOCK_LIB] Entering intentional infinite loop...\n");
  while (1) {
    sleep(1);
  }
}
