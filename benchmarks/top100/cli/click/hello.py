import click


@click.command()
def cli():
    click.echo(f"Click version: {click.__version__}")


if __name__ == "__main__":
    try:
        cli(standalone_mode=False)
    except:
        pass
print(f"Click version: {click.__version__}")
