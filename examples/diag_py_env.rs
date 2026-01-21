use std::path::PathBuf;
use velo::common::python_env::PythonEnv;

fn main() {
    let python = std::env::var("VELO_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let python_path = PathBuf::from(python);

    match PythonEnv::detect(&python_path) {
        Ok(env) => {
            println!("Base Prefix: {:?}", env.base_prefix);
            println!("Version: {}", env.version);
            println!("Lib Dir: {:?}", env.lib_dir);
            println!("Venv Root: {:?}", env.venv_root);

            let mut cmd = std::process::Command::new("env");
            env.apply_to_command(&mut cmd);
            println!("Envs: {:?}", cmd.get_envs().collect::<Vec<_>>());
        }
        Err(e) => {
            eprintln!("Error: {}", e);
        }
    }
}
