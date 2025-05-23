# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_gpf_slr.ipynb.

# %% auto 0
__all__ = ['extract_initial_seed_indices', 'estimate_ground_plane', 'refine_ground_plane', 'group_by_scanline', 'find_runs',
           'update_labels', 'extract_clusters', 'scan_line_run_clustering']

# %% ../nbs/01_gpf_slr.ipynb 3
import numpy as np
from sklearn.neighbors import KDTree

# %% ../nbs/01_gpf_slr.ipynb 5
def extract_initial_seed_indices(
    point_cloud: np.ndarray, num_points: int = 1000, height_threshold: float = 0.4
) -> np.ndarray:
    """
    Extract initial seed points for ground plane estimation (GPF).

    Args:
        point_cloud (np.ndarray): N x 3 array of points (x, y, z).
        num_points (int): number of lowest Z points to average as LPR.
        height_threshold (float): threshold to select seeds close to LPR height.

    Returns:
        seeds_ids (np.ndarray): indices of points selected as initial seeds.
    """

    # Step 1: Sort the point cloud by Z axis (height)
    sorted_indices = np.argsort(point_cloud[:, 2])  # Get indices sorted by height
    sorted_points = point_cloud[sorted_indices]  # Apply sorting

    # Step 2: Compute LPR (Lowest Point Representative)
    lpr_height = np.mean(sorted_points[:num_points, 2])

    # Step 3: Select point ids that are within threshold distance from LPR
    mask = sorted_points[:, 2] < (lpr_height + height_threshold)
    return sorted_indices[mask]

# %% ../nbs/01_gpf_slr.ipynb 6
def estimate_ground_plane(points: np.ndarray) -> "tuple[np.ndarray, float]":
    """
    Estimate the ground plane parameters using Singular Value Decomposition (SVD).

    Args:
        points (np.ndarray): N x 3 array (x, y, z) of seed points assumed to be on or near the ground.

    Returns:
        tuple:
            - normal (np.ndarray): Normal vector (a, b, c) of the estimated ground plane.
            - d (float): Offset term of the estimated plane equation (ax + by + cz + d = 0).
    """

    # Step 1: Compute centroid of the seed points
    centroid = np.mean(points, axis=0)
    centered_points = points - centroid

    # Step 2: Compute the covariance matrix of centered points
    covariance_matrix = np.cov(centered_points.T)

    # Step 3: Perform SVD on the covariance matrix to extract principal directions
    _, _, vh = np.linalg.svd(covariance_matrix)

    # Step 4: Normal vector is the direction with smallest variance (last column of V^T)
    normal = vh[-1]

    # Step 5: Compute plane bias using point-normal form: ax + by + cz + d = 0
    d = -np.dot(normal, centroid)

    return (normal, d)

# %% ../nbs/01_gpf_slr.ipynb 7
def refine_ground_plane(
    point_cloud: np.ndarray,
    num_points: int = 1000,
    height_threshold: float = 0.4,
    distance_threshold: float = 0.2,
    num_iterations: int = 5,
) -> "tuple[np.ndarray, tuple[np.ndarray, float]]":
    """
    Iteratively refine the ground plane estimation using seed points and distance threshold.

    Args:
        point_cloud (np.ndarray): Nx6 array [x, y, z, true_label, pred_label, scanline_id].
        num_points (int): Number of lowest Z points used to compute the initial ground seed height (LPR).
        height_threshold (float): Vertical distance threshold from the LPR used to select initial seed points.
        distance_threshold (float): Max allowed point-to-plane distance for a point to be considered ground.
        num_iterations (int): Number of iterations to refine the plane and ground classification.

    Returns:
        tuple:
            - point_cloud (np.ndarray): Nx6 array [x, y, z, true_label, pred_label, scanline_id], input array with ground points labeled.
            - normal (np.ndarray): Normal vector (a, b, c) of the estimated ground plane.
            - d (float): Offset term of the estimated plane equation (ax + by + cz + d = 0).
    """

    # Step 0: Use only XYZ for plane estimation
    xyz = point_cloud[:, :3]

    # Step 1: Get initial seed points based on lowest Z values
    seed_indices = extract_initial_seed_indices(xyz, num_points, height_threshold)

    for _ in range(num_iterations):
        # Step 2: Estimate ground plane using current seeds
        normal, d = estimate_ground_plane(xyz[seed_indices])

        # Step 3: Compute distances from all points to the estimated plane
        distances = np.abs(np.dot(xyz, normal) + d) / np.linalg.norm(normal)

        # Step 4: Classify as ground if within distance threshold
        is_ground = distances < distance_threshold

        # Step 5: Update seeds with newly classified ground points
        seed_indices = np.where(is_ground)[0]

    # Final ground classification using last iteration's result
    point_cloud[seed_indices, 4] = 9  # Set label = 9 for ground

    return (point_cloud, (normal, d))

# %% ../nbs/01_gpf_slr.ipynb 9
def group_by_scanline(point_cloud: np.ndarray) -> "list[np.ndarray]":
    """
    Group points by their scanline index in a vectorized way.

    Args:
        point_cloud (np.ndarray): N x 6 array [x, y, z, true_label, pred_label, scanline_id].

    Returns:
        list[np.ndarray]: List of arrays. Each array contains the points (N_i x 6)
                          from one scanline, sorted by scanline_id.
    """
    scan_ids = point_cloud[:, 5].astype(int)
    unique_ids = np.unique(scan_ids)

    return [point_cloud[scan_ids == s_id] for s_id in unique_ids]

# %% ../nbs/01_gpf_slr.ipynb 10
def find_runs(
    scanline_points: np.ndarray, distance_threshold: float = 0.5
) -> "list[np.ndarray]":
    """
    Identify runs within a single scanline based on distance between consecutive points.

    Args:
        scanline_points (np.ndarray): N x 6 array [x, y, z, true_label, pred_label, scanline_id].
        distance_threshold (float): Distance threshold to consider two points part of the same run.

    Returns:
        list[np.ndarray]: List of arrays where each array contains the points of a run.
    """
    num_points = len(scanline_points)
    runs = []
    current_run_indices = [0]  # start with the index of the first point

    for i in range(1, num_points):
        dist = np.linalg.norm(scanline_points[i, :3] - scanline_points[i - 1, :3])
        if dist < distance_threshold:
            current_run_indices.append(i)
        else:
            runs.append(scanline_points[current_run_indices])
            current_run_indices = [i]

    # append the last run
    runs.append(scanline_points[current_run_indices])

    # Check if first and last points are close (circular case)
    circular_dist = np.linalg.norm(scanline_points[0, :3] - scanline_points[-1, :3])
    # Only merge runs if:
    # - the scanline appears to be circular (first and last points are close), and
    # - there is more than one run (otherwise merging doesn't make sense)
    if circular_dist < distance_threshold and len(runs) > 1:
        # Merge last run with the first
        runs[0] = np.vstack((runs[-1], runs[0]))
        runs.pop()

    return runs

# %% ../nbs/01_gpf_slr.ipynb 11
def update_labels(
    runs_current: "list[np.ndarray]",
    runs_above: "list[np.ndarray]",
    label_equivalences: dict,
    merge_threshold: float = 1.0,
):
    """
    Update labels of current scanline runs based on proximity to runs from previous scanline using KDTree.

    Args:
        runs_current (list[np.ndarray]): List of N x 6 arrays for current scanline runs.
        runs_above (list[np.ndarray]): List of N x 6 arrays for previous scanline runs.
        label_equivalences (dict): Dictionary of label equivalences.
        merge_threshold (float): Maximum distance to consider connection between runs.
    """

    def resolve_label(label: int) -> int:
        """Find the final label by following the equivalence chain."""
        while label != label_equivalences[label]:
            label = label_equivalences[label]
        return label

    def assign_new_label(run, label_equivalences, global_label_counter):
        while global_label_counter == 9 or global_label_counter in label_equivalences:
            global_label_counter += 1
        run[:, 4] = global_label_counter
        label_equivalences[global_label_counter] = global_label_counter
        return global_label_counter + 1

    def inherit_and_unify_labels(run, neighbor_labels, label_equivalences):
        min_label = min(neighbor_labels)
        run[:, 4] = min_label
        for lbl in neighbor_labels:
            label_equivalences[lbl] = min_label

    global_label_counter = max(label_equivalences.values()) + 1

    points_above = np.vstack(runs_above)
    tree_above = KDTree(points_above[:, :3])  # use only x, y, z

    for run in runs_current:
        neighbor_labels = set()
        dists, indices = tree_above.query(run[:, :3], k=1)
        close_mask = dists[:, 0] < merge_threshold
        close_indices = indices[close_mask, 0]
        if close_indices.size > 0:
            for idx in close_indices:
                neighbor_label = points_above[idx, 4]
                resolved_label = resolve_label(neighbor_label)
                neighbor_labels.add(resolved_label)
        if not neighbor_labels:
            global_label_counter = assign_new_label(
                run, label_equivalences, global_label_counter
            )
        else:
            inherit_and_unify_labels(run, neighbor_labels, label_equivalences)

# %% ../nbs/01_gpf_slr.ipynb 12
def extract_clusters(
    scanlines: "list[np.ndarray]", label_equivalences: dict
) -> np.ndarray:
    """
    Apply resolved labels to all points and return a unified point cloud.

    Args:
        scanlines (list[np.ndarray]): List of N x 6 arrays for each scanline.
        label_equivalences (dict): Dictionary of final label equivalences.

    Returns:
        np.ndarray: N x 6 array with updated labels in column 4.
    """
    non_ground_points = np.vstack(scanlines)

    for idx in range(0, len(non_ground_points)):
        non_ground_points[idx][4] = label_equivalences[non_ground_points[idx][4]]

    return non_ground_points

# %% ../nbs/01_gpf_slr.ipynb 13
def scan_line_run_clustering(
    point_cloud: np.ndarray,
    distance_threshold: float = 0.5,
    merge_threshold: float = 1.0,
) -> np.ndarray:
    """
    Perform scan line run clustering on non-ground points (predicted_label == 0).

    This function detects connected components (runs) within scanlines, propagates
    and merges labels across scanlines, and assigns final labels to each point.

    Args:
        point_cloud (np.ndarray): N x 6 array [x, y, z, true_label, predicted_label, scanline_index].
        distance_threshold (float): Distance threshold to consider two points part of the same run.
        merge_threshold (float): Maximum distance to consider connection between runs.

    Returns:
        np.ndarray: Point cloud with updated predicted labels (column 4).
    """
    label_counter = 0
    label_equivalences = {}

    # Filter non-ground points (predicted_label == 0)
    non_ground_mask = point_cloud[:, 4] == 0
    if non_ground_mask.sum() == 0:
        raise ValueError("point cloud já clusterizada")
    non_ground_indices = np.nonzero(non_ground_mask)[0]  # ← Adicionada
    non_ground_points = point_cloud[non_ground_mask].copy()

    if non_ground_points.size == 0:
        raise ValueError("Point cloud already clustered or no non-ground points found.")
    # Group points into scanlines
    scanlines = group_by_scanline(non_ground_points)

    # Initialize clustering with the first scanline
    runs_above = find_runs(scanlines[0], distance_threshold)
    for runs in runs_above:
        label_counter += 1
        if label_counter == 9:  # reserve label 9 for ground
            label_counter += 1
        runs[:, 4] = label_counter
        label_equivalences[label_counter] = label_counter

    scanlines[0] = np.vstack(runs_above)

    # Propagate labels through remaining scanlines
    for i in range(1, len(scanlines)):
        runs_current = find_runs(scanlines[i], distance_threshold)
        update_labels(runs_current, runs_above, label_equivalences, merge_threshold)

        scanlines[i] = np.vstack(runs_current)
        runs_above = runs_current

    clustered_points = extract_clusters(scanlines, label_equivalences)
    point_cloud[non_ground_indices, 4] = clustered_points[:, 4]
    return point_cloud
