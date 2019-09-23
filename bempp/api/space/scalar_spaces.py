"""Definition of scalar function spaces."""

import numpy as _np
import numba as _numba


def p0_discontinuous_function_space(grid, support_elements=None, segments=None, swapped_normals=None):
    """Define a space of piecewise constant functions."""
    from .space import SpaceBuilder, _process_segments, invert_local2global

    support, normal_multipliers = _process_segments(grid, support_elements, segments, swapped_normals)

    elements_in_support = _np.flatnonzero(support)
    support_size = len(elements_in_support)

    local2global = _np.zeros((grid.number_of_elements, 1), dtype="uint32")
    local2global[support] = _np.expand_dims(
        _np.arange(support_size, dtype="uint32"), 1
    )

    local_multipliers = _np.zeros((grid.number_of_elements, 1), dtype="float64")
    local_multipliers[support] = 1

    global2local = invert_local2global(local2global, local_multipliers)

    collocation_points = _np.array([[1./3], [1./3]])

    return SpaceBuilder(grid).set_codomain_dimension(1) \
            .set_support(support) \
            .set_normal_multipliers(normal_multipliers) \
            .set_order(0) \
            .set_shapeset("p0_discontinuous") \
            .set_identifier("p0_discontinuous") \
            .set_local2global(local2global) \
            .set_global2local(global2local) \
            .set_local_multipliers(local_multipliers) \
            .set_collocation_points(collocation_points) \
            .set_numba_surface_gradient(_numba_p0_surface_gradient) \
            .build()

def p1_discontinuous_function_space(grid, support_elements=None, segments=None, swapped_normals=None):
    """Define a discontinuous space of piecewise linear functions."""

    from .space import SpaceBuilder, _process_segments, invert_local2global

    support, normal_multipliers = _process_segments(grid, support_elements, segments, swapped_normals)

    elements_in_support = _np.flatnonzero(support)
    support_size = len(elements_in_support)

    local2global = _np.zeros((grid.number_of_elements, 3), dtype="uint32")
    local2global[support] = _np.arange(3 * support_size).reshape(
            support_size, 3)

    local_multipliers = _np.zeros((grid.number_of_elements, 3), dtype="float64")
    local_multipliers[support] = 1

    global2local = invert_local2global(local2global, local_multipliers)

    return SpaceBuilder(grid).set_codomain_dimension(1) \
            .set_support(support) \
            .set_normal_multipliers(normal_multipliers) \
            .set_order(1) \
            .set_shapeset("p1_discontinuous") \
            .set_identifier("p1_discontinuous") \
            .set_local2global(local2global) \
            .set_global2local(global2local) \
            .set_local_multipliers(local_multipliers) \
            .set_numba_surface_gradient(_numba_p1_surface_gradient) \
            .build()

def p1_continuous_function_space(
        grid, support_elements=None, segments=None, swapped_normals=None,
        include_boundary_dofs=False, ensure_global_continuity=False):
    """Define a space of continuous piecewise linear functions."""
    import bempp.api
    from .space import SpaceBuilder, _process_segments, invert_local2global
    from bempp.api.utils.helpers import serialise_list_of_lists

    shapeset = "p1_discontinuous"
    number_of_elements = grid.number_of_elements
    support, normal_multipliers = _process_segments(grid, support_elements, segments, swapped_normals)

    elements_in_support = _np.flatnonzero(support)
    support_size = len(elements_in_support)

    # Create list of vertex neighbors. Needed for dofmap computation

    vertex_neighbors = [[] for _ in range(grid.number_of_vertices)]
    for index in range(grid.number_of_elements):
        for vertex in grid.elements[:, index]:
            vertex_neighbors[vertex].append(index)
    vertex_neighbors, index_ptr = serialise_list_of_lists(vertex_neighbors)

    local2global, local_multipliers = _compute_p1_dof_map(
            grid.data, support, include_boundary_dofs, ensure_global_continuity,
            vertex_neighbors, index_ptr)

    global2local = invert_local2global(local2global, local_multipliers)

    return SpaceBuilder(grid).set_codomain_dimension(1) \
            .set_support(support) \
            .set_normal_multipliers(normal_multipliers) \
            .set_order(1) \
            .set_shapeset("p1_discontinuous") \
            .set_identifier("p1_continuous") \
            .set_local2global(local2global) \
            .set_global2local(global2local) \
            .set_local_multipliers(local_multipliers) \
            .set_numba_surface_gradient(_numba_p1_surface_gradient) \
            .build()

@_numba.njit(cache=True)
def _compute_p1_dof_map(grid_data, support, include_boundary_dofs, ensure_global_continuity,
        vertex_neighbors, index_ptr):
    """Compute the local2global and local_multipliers maps for P1 space."""

    def find_index(array, value):
        """Return first position of value in array."""
        for index, val in enumerate(array):
            if val == value: return index
        return -1

    elements_in_support = []
    for index, val in enumerate(support):
        if val: elements_in_support.append(index)

    number_of_elements = grid_data.elements.shape[1]
    number_of_vertices = grid_data.vertices.shape[1]
    local2global = -_np.ones((number_of_elements, 3), dtype=_np.int32)
    
    vertex_is_dof = _np.zeros(number_of_vertices, dtype=_np.bool_)
    delete_from_support = []

    for element_index in elements_in_support:
        for local_index in range(3):
            vertex = grid_data.elements[local_index, element_index]
            neighbors = vertex_neighbors[index_ptr[vertex] : index_ptr[vertex + 1]]
            non_support_neighbors = [n for n in neighbors if not support[n]]
            if include_boundary_dofs or len(non_support_neighbors) == 0:
                # Just add dof
                local2global[element_index, local_index] = vertex
                vertex_is_dof[vertex] = True
            if (len(non_support_neighbors) > 0 and 
                    ensure_global_continuity and include_boundary_dofs):
                elements_in_support.extend(non_support_neighbors)
                for en in non_support_neighbors:
                    other_local_index = find_index(grid_data.elements[:, en], vertex)
                    local2global[en, other_local_index] = vertex
                    # vertex_is_dof was already set to True in previous if.

    # We have now all the vertices that have dofs attached and local2global
    # has the vertex index if it is used and -1 otherwise.

    # Now need to convert vertex indices into actual dof indices. For subgrids
    # these two are not identical.


    support_final = _np.zeros(number_of_elements, dtype=_np.bool_)
    local2global_final = _np.zeros((number_of_elements, 3), dtype=_np.uint32)
    local_multipliers = _np.zeros((number_of_elements, 3), dtype=_np.float64)

    dofs = -_np.ones(number_of_vertices)
    used_dofs = _np.flatnonzero(vertex_is_dof)
    global_dof_count = len(used_dofs)
    dofs[used_dofs] = _np.arange(global_dof_count)


    # Iterate through all support elements and replace vertex indices by
    # dof indices

    for element_index in elements_in_support:
        for local_index in range(3):
            vertex_index = local2global[element_index, local_index]
            if vertex_index == -1: continue
            mapped_dof = dofs[vertex_index]
            support_final[element_index] = True
            local2global_final[element_index, local_index] = mapped_dof
            local_multipliers[element_index, local_index] = 1
        # If not every local index was used in a grid we need to
        # map the non-used local dofs to some global dof. Use the
        # one with minimal index in element. The corresponding
        # multipliers are set to zero so that these artificial dofs
        # do not influence computations.
        min_dof = _np.min(local2global_final[element_index])
        for local_index in range(3):
            if local2global[element_index, local_index] == -1:
                local2global_final[element_index, local_index] = min_dof

    return local2global_final, local_multipliers

        
@_numba.njit
def _numba_p0_surface_gradient(
    element_index, shapeset_gradient, local_coordinates, grid_data, local_multipliers, normal_multipliers
):
    """Evaluate the surface gradient."""
    return _np.zeros((1, 3, 1, local_coordinates.shape[1]), dtype=_np.float64)

@_numba.njit
def _numba_p1_surface_gradient(
    element_index, shapeset_gradient, local_coordinates, grid_data, local_multipliers, normal_multipliers
):
    """Evaluate the surface gradient."""
    reference_values = shapeset_gradient(local_coordinates)
    result = _np.empty((1, 3, 3, local_coordinates.shape[1]), dtype=_np.float64)
    for index in range(3):
        result[0, :, index, :] = grid_data.jac_inv_trans[element_index].dot(
            reference_values[0, :, index, :]
        )
    return result