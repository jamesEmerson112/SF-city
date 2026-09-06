use godot::prelude::*;

const MAX_INSTANCES: usize = 100_000;
const MAX_PARTS: usize = 32;
const STRIDE: usize = 20;

struct CivicGodotExtension;

#[gdextension]
unsafe impl ExtensionLibrary for CivicGodotExtension {}

#[derive(GodotClass)]
#[class(init, base=RefCounted)]
struct CivicCrowdBuffers {
    base: Base<RefCounted>,
    part_colors: Vec<Vec<Color>>,
    error_message: GString,
}

#[godot_api]
impl CivicCrowdBuffers {
    #[func]
    fn protocol_version(&self) -> i64 {
        1
    }

    #[func]
    fn get_error_message(&self) -> GString {
        self.error_message.clone()
    }

    /// Freeze appearance once in stable slot order. No resident IDs or domain
    /// state enter the extension, and invalid input retains prior configuration.
    #[func]
    fn configure_colors(&mut self, colors: Array<PackedColorArray>) -> bool {
        self.error_message = GString::new();
        if colors.len() > MAX_PARTS {
            self.error_message = "Crowd part count exceeds its bound.".into();
            return false;
        }
        let count = colors.get(0).map_or(0, |values| values.len());
        if count > MAX_INSTANCES || colors.iter_shared().any(|values| values.len() != count) {
            self.error_message = "Crowd part colors do not share bounded stable slots.".into();
            return false;
        }
        self.part_colors = colors
            .iter_shared()
            .map(|values| values.as_slice().to_vec())
            .collect();
        true
    }

    /// Pack the exact roots/custom flags supplied by GDScript. Shader gait,
    /// visibility decisions, picking and camera following remain in GDScript.
    #[func]
    fn build_buffers(
        &mut self,
        roots: Array<Transform3D>,
        custom: PackedColorArray,
    ) -> Array<PackedFloat32Array> {
        self.error_message = GString::new();
        let mut result = Array::new();
        let count = roots.len();
        if count > MAX_INSTANCES
            || custom.len() != count
            || self
                .part_colors
                .first()
                .is_some_and(|values| values.len() != count)
        {
            self.error_message =
                "Crowd transforms, flags and colors do not share stable slots.".into();
            return result;
        }
        if self.part_colors.is_empty() {
            return result;
        }
        let mut common = vec![0.0f32; count * STRIDE];
        for (index, (pose, flags)) in roots.iter_shared().zip(custom.as_slice()).enumerate() {
            let offset = index * STRIDE;
            let origin = [pose.origin.x, pose.origin.y, pose.origin.z];
            // gdext Basis stores rows, matching MultiMesh's documented layout.
            for row in 0..3 {
                let axis = pose.basis.rows[row];
                common[offset + row * 4..offset + row * 4 + 3]
                    .copy_from_slice(&[axis.x, axis.y, axis.z]);
                common[offset + row * 4 + 3] = origin[row];
            }
            common[offset + 16..offset + 20].copy_from_slice(&[flags.r, flags.g, flags.b, flags.a]);
        }
        for colors in &self.part_colors {
            let mut buffer = PackedFloat32Array::from(common.as_slice());
            let values = buffer.as_mut_slice();
            for (index, tint) in colors.iter().enumerate() {
                let offset = index * STRIDE + 12;
                values[offset..offset + 4].copy_from_slice(&[tint.r, tint.g, tint.b, tint.a]);
            }
            result.push(&buffer);
        }
        result
    }
}
