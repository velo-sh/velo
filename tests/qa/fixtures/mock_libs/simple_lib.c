#include <stdio.h>

void __attribute__((constructor)) init(void) {
  fprintf(stderr, "[MOCK_LIB] Normal library initialized.\n");
}

int add(int a, int b) { return a + b; }
