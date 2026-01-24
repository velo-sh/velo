#include <stdio.h>

// 256MB of static data to force COW sharing opportunities
char large_data[256 * 1024 * 1024] = {1};

void __attribute__((constructor)) init(void) {
  fprintf(stderr, "[LARGE_LIB] Large library initialized (256MB).\n");
  // Touch data to ensure it's mapped
  large_data[0] = 42;
  large_data[256 * 1024 * 1024 - 1] = 42;
}

int get_data(int index) { return large_data[index]; }
