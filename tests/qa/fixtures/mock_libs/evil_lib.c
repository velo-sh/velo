#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

void __attribute__((constructor)) init(void) {
  // 1. Child Leakage test
  if (fork() == 0) {
    // Child of the vet process
    fprintf(stderr, "[MOCK_EVIL] Leaking background child...\n");
    sleep(60);
    exit(0);
  }

  // 2. Excessive Memory test
  fprintf(stderr, "[MOCK_EVIL] Allocating 512MB...\n");
  void *p = mmap(NULL, 512 * 1024 * 1024, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANON, -1, 0);
  if (p != MAP_FAILED) {
    // Touch it to ensure it's actually allocated
    ((char *)p)[0] = 1;
  }

  // 3. File System Probe
  fprintf(stderr, "[MOCK_EVIL] Probing /tmp/velo_probe...\n");
  FILE *f = fopen("/tmp/velo_probe", "w");
  if (f) {
    fprintf(f, "pwned");
    fclose(f);
  }
}
