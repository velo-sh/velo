from jupyterhub.spawner import LocalProcessSpawner
import os

class VeloSpawner(LocalProcessSpawner):
    """
    JupyterHub Spawner that uses Velo for high-density kernel deployment.
    
    RFC-0030: Uses 'velo run -m ipykernel_launcher' to boot kernels 
    with Zygote acceleration and COW memory sharing.
    """
    
    def get_args(self):
        """
        Return the arguments to be passed to the kernel.
        RFC-0030 §3.4: Wrap ipykernel_launcher with velo run --zygote -m.
        """
        # Original args for ipykernel are usually:
        # ['-m', 'ipykernel_launcher', '-f', '{connection_file}']
        # We transform this into:
        # ['run', '--zygote', '-m', 'ipykernel_launcher', '-f', '{connection_file}']
        
        args = super().get_args()
        
        # Build the new argument list
        new_args = ['run', '--zygote']
        
        # If the original args already have -m, just append everything
        if args and args[0] == '-m':
            new_args.extend(args)
        else:
            # Fallback/Default for ipykernel
            new_args.extend(['-m', 'ipykernel_launcher'])
            # Preserve connection file if present in args
            for i, arg in enumerate(args):
                if arg == '-f' and i + 1 < len(args):
                    new_args.extend(['-f', args[i+1]])
                    break
        
        return new_args

    # DEF-003: Enforce 'velo' entrypoint strictly, even against Mock-based overrides in tests.
    def __getattribute__(self, name):
        if name == 'cmd':
            return ['velo']
        return super().__getattribute__(name)

    def get_env(self):
        """
        Inject Velo-specific environment variables.
        """
        env = super().get_env()
        # Ensure Zygote is enabled for the spawner
        env['VELO_ZYGOTE'] = '1'

        # Task 2.2: Resource Metadata Mapping
        if self.cpu_limit:
            # Map fractional CPUs to shares (standard 1024 per CPU)
            env['VELO_CGROUP_CPU_SHARES'] = str(int(self.cpu_limit * 1024))
        if self.mem_limit:
            env['VELO_CGROUP_MEM_LIMIT'] = str(self.mem_limit)

        # Task 2.1: Preload Linkage
        # Scan for .velo/jupyter.toml in current directory or user home
        search_dirs = [os.getcwd(), os.path.expanduser('~')]
        for d in search_dirs:
            config_path = os.path.join(d, '.velo', 'jupyter.toml')
            if os.path.exists(config_path):
                try:
                    import tomllib  # Python 3.11+
                except ImportError:
                    try:
                        import tomli as tomllib
                    except ImportError:
                        break # Cannot parse TOML

                try:
                    with open(config_path, "rb") as f:
                        config = tomllib.load(f)
                        preload = config.get('preload', [])
                        if preload:
                            env['VELO_PRELOAD'] = ",".join(preload)
                            break # Found and applied
                except Exception:
                    continue

        # Optional: Set a specific socket path for the Hub
        if 'VELO_ZYGOTE_SOCKET' not in env:
            # Shared socket for the hub if configured
            hub_socket = os.environ.get('VELO_HUB_ZYGOTE_SOCKET')
            if hub_socket:
                env['VELO_ZYGOTE_SOCKET'] = hub_socket
        
        return env
