---
name: Pepper's Cone DIY 3D Display
description: A low-cost, do-it-yourself 3D display using a tablet and a plastic cone reflector to create a perspective-correct view of a 2D image from any angle.
updated: 1795039651
sources: /home/connor/Projects/Ada/data/uploads/Pepper_s_Cone_UIST_2017.pdf
---

# Summary
The Pepper's Cone is an inexpensive, DIY volumetric-style display that creates the illusion of a 3D object suspended inside a transparent cone. It utilizes a standard tablet computer (like an iPad) and a thin, hollow plastic sheet folded into a cone shape. By reflecting the tablet screen through the curved surface of the cone, the system renders a perspective-correct image for the viewer's specific point of view, allowing interaction with the 3D scene over a full 360-degree path without special glasses.

# Key Concepts and Optical Principles
- **Pepper's Ghost Illusion**: The core technology is based on the classic 19th-century stage technique where an image projected onto a hidden screen is reflected by a semi-transparent surface (the cone) to appear as if it exists in physical space.
- **Curved Reflector Geometry**: Unlike traditional Pepper's Ghost setups which use flat mirrors, this system uses a curved conic surface. The specific geometry (a 51-degree cone for an iPad Pro) was determined by analyzing rotationally-symmetric conic surfaces to optimize optical performance and stereo-compatibility.
- **Pre-distortion and Warping**: Because the cone distorts the reflected image, the software must pre-warp the content displayed on the tablet. This compensates for the distortion so that when viewed through the reflector, the object appears geometrically correct and perspective-accurate to the user's eye position.
- **Gyroscope Integration**: Modern tablets include gyroscopes that detect the rotation of the device. The system queries this sensor to adjust the rendered image in real-time based on the relative orientation of the viewer, enabling smooth interactive viewing as the user rotates the display.

# Important Facts and Details
- **Cost and Build Time**: The entire setup can be built in an afternoon for a minimal cost beyond the price of the tablet computer itself. Prototypes have been successfully made using common items like plastic cups or folded plastic sheets.
- **Resolution and Quality**: The system leverages the high resolution and frame rates of modern tablet displays to accurately reproduce view-dependent effects, such as specular highlights (e.g., shiny surfaces on a car model), which many volumetric displays struggle with.
- **Stereo Compatibility**: While the basic setup is stereo-compatible (allowing both eyes to see the same image), there can be a mismatch between binocular and monocular cues. To eliminate this conflict and enhance depth perception, the system supports "binocular correction" using simple Red-Blue anaglyph glasses to project separate images to each eye.
- **Viewing Experience**: The user sees a distorted reflection of the display from the side that appears to be located inside the reflector. As the user rotates the cone around the tablet, the image updates to maintain the illusion of a solid 3D object floating within the cone.

# Procedures and Steps
1. **Hardware Assembly**: Obtain a tablet with a gyroscope (e.g., iPad Pro) and a transparent material (plastic sheet or clear plastic cup). Fold or shape the material into a truncated cone resting on the tablet screen.
2. **Software Calibration**: Run the accompanying software which analyzes the optical properties of your specific reflector geometry.
3. **Image Rendering**: The system pre-distorts the 3D model or image being displayed to compensate for the cone's curvature.
4. **Interaction**: Rotate the physical cone around the tablet. The gyroscope detects this movement, and the rendering engine updates the perspective-correct image instantly, maintaining the illusion of a suspended object.
5. **Optional Stereo Upgrade**: For enhanced depth perception, add Red-Blue anaglyph glasses to enable binocular correction, projecting separate images for each eye.

# Takeaways and Applications
This technology democratizes access to volumetric-style visualization. It is suitable for applications in education (visualizing complex 3D structures), medicine (viewing anatomical models), art exhibitions, product design reviews, telepresence, and virtual assistants. It offers a natural user experience that avoids head-mounted displays or expensive light field setups while still providing convincing 3D cues.

# Limitations and Notes
- **Stereo Fusion**: Without anaglyph glasses, the system relies on monocular cues for depth, which can sometimes conflict with binocular expectations, though the cone geometry is optimized to minimize this.
- **Reflective Surface Quality**: The clarity of the 3D illusion depends heavily on the transparency and reflectivity of the chosen plastic material; scratches or dirt on the cone will degrade the image quality.
- **Viewing Angle**: While it supports a 360-degree path, the optimal viewing experience is achieved when looking through the transparent surface rather than from directly above or below depending on the specific cone orientation.
