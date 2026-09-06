from openglassbox.script_parser import Script

def main():
    simfile = "demo/data/Simulations/TestCity.txt"
    script = Script()
    print(f"Attempting to parse: {simfile}")
    result = script.parse(simfile)
    print(f"Parse result: {result}")
    if result:
        print("Parsing succeeded.")
        # Print some details about the parsed script
        print(f"Resources: {getattr(script, 'm_resources', None)}")
        print(f"Maps: {getattr(script, 'm_maps', None)}")
        print(f"Paths: {getattr(script, 'm_paths', None)}")
        print(f"Units: {getattr(script, 'm_units', None)}")
        print(f"Rules: {getattr(script, 'm_rules', None)}")
    else:
        print("Parsing failed.")

if __name__ == "__main__":
    main()
