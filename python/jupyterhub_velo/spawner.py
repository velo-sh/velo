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
        RFC-0030 §3.4: Wrap ipykernel_launcher with velo run -m.
        """
        # Original args for ipykernel are usually:
        # ['-m', 'ipykernel_launcher', '-f', '{connection_file}']
        # We want to transform 'python' into 'velo' and add 'run'.
        
        # LocalProcessSpawner usually runs 'python -m ipykernel_launcher ...'
        # if the kernelspec says so. 
        # But if the kernelspec ALREADY says 'velo run -m ...',
        # then we don't need to do much.
        
        # However, VeloSpawner's value-add is ensuring Zygote is used 
        # and handling any environment-specific overrides for high density.
        
        args = super().get_args()
        return args

    @property
    def cmd(self):
        """
        Return the command to be run.
        RFC-0030: Always use 'velo' as the entry point.
        """
        # If the kernelspec is already set to 'velo', this might be redundant,
        # but VeloSpawner enforces it for all users on the Hub.
        return ['velo']

    def get_env(self):
        """
        Inject Velo-specific environment variables.
        """
        env = super().get_env()
        # Ensure Zygote is enabled for the spawner
        env['VELO_ZYGOTE'] = '1'
        # Optional: Set a specific socket path for the Hub
        if 'VELO_ZYGOTE_SOCKET' not in env:
            # Shared socket for the hub if configured
            hub_socket = os.environ.get('VELO_HUB_ZYGOTE_SOCKET')
            if hub_socket:
                env['VELO_ZYGOTE_SOCKET'] = hub_socket
        
        return env
